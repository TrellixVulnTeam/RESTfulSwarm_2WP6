#!/usr/bin/env /usr/local/bin/python
# encoding: utf-8
# Author: Zhuangwei Kang

import os
import multiprocessing
import threading
import requests
import json
import argparse
import random
import math
import time

from live_migration import LiveMigration
import docker_api as docker
import zmq_api as zmq
import utl
import SystemConstants


class Worker:
    def __init__(self, gm_address, worker_address, dis_address, task_monitor_frequency):
        self.logger = utl.get_logger('WorkerLogger', 'worker.log')
        self.swarm_socket = zmq.ps_connect(gm_address, SystemConstants.GM_PUB_PORT)
        self.docker_client = docker.set_client()
        self.gm_address = gm_address
        self.host_address = worker_address
        self.hostname = utl.get_hostname()
        zmq.subscribe_topic(self.swarm_socket, self.hostname)
        zmq.subscribe_topic(self.swarm_socket, self.host_address)

        # local storage
        # format: {$container : $containerInfo}
        self.storage = {}

        self.dis_address = dis_address
        self.task_monitor_frequency = task_monitor_frequency

    def monitor(self, dis_address, frequency=0.1):
        client = docker.set_client()
        time.sleep(frequency)
        hostname = utl.get_hostname()
        socket = zmq.cs_connect(dis_address, SystemConstants.DISCOVERY_PORT)
        time_end = math.floor(time.time())
        deployed_tasks = []
        while True:
            try:
                time_start = math.ceil(time.time())
                events = client.events(since=time_end,
                                       until=time_start,
                                       filters={'type': 'container',
                                                'event': 'die'},
                                       decode=True)
                time_end = math.floor(time.time())

                msgs = []
                for event in events:
                    if event['Actor']['Attributes']['name'] in self.storage.keys() and \
                            event['Actor']['Attributes']['name'] not in deployed_tasks:
                        msg = hostname + ' ' + event['Actor']['Attributes']['name']
                        deployed_tasks.append(event['Actor']['Attributes']['name'])
                        msgs.append(msg)

                events.close()

                # 去重
                msgs = list(set(msgs))

                if len(msgs) != 0:
                    msgs = ','.join(msgs)
                    # Notify discovery block to update MongoDB
                    self.logger.info('Discovery: %s' % msgs)
                    socket.send_string(msgs)
                    socket.recv_string()

                time.sleep(frequency)

            except Exception as ex:
                self.logger.debug(ex)

    def listen_manager_msg(self):
        while True:
            try:
                msg = self.swarm_socket.recv_string()
                msg = msg.split()[1:]
                msg_type = msg[0]
                if msg_type == 'join':
                    remote_address = msg[1]
                    join_token = msg[2]
                    self.join_swarm(remote_address, join_token)
                elif msg_type == 'checkpoints':
                    data = json.loads(' '.join(msg[1:]))
                    threads = []
                    for i in range(0, len(data)):
                        checkpoint_name = data[i] + '_' + str(random.randint(1, 1000))
                        container_id = docker.get_container_id(self.docker_client, data[i])
                        thr = threading.Thread(target=docker.checkpoint, args=(checkpoint_name, container_id, True,))
                        thr.setDaemon(True)
                        threads.append(thr)

                    map(lambda _thr: _thr.start(), threads)
                elif msg_type == 'migrate':
                    info = json.loads(' '.join(msg[1:]))
                    dst = info['dst']
                    container = info['container']
                    container_info = info['info']
                    container_info['node'] = self.hostname
                    try:
                        temp_container = self.storage[container]
                        del self.storage[container]
                        try:
                            lm_controller = LiveMigration(image=temp_container['image'], name=container,
                                                          network=temp_container['network'], logger=self.logger,
                                                          docker_client=self.docker_client)
                            lm_controller.migrate(dst_address=dst, cmd=temp_container['command'],
                                                  container_detail=container_info)
                        except Exception as ex:
                            self.logger.error(ex)
                            self.storage.update({container: temp_container})
                    except Exception as ex:
                        self.logger.error(ex)
                elif msg_type == 'new_container':
                    info = json.loads(' '.join(msg[1:]))
                    container_name = info['container_name']
                    del info['node']
                    self.storage.update({container_name: info})
                    job_name = container_name.split('_')[0]
                    volume_dir = '/nfs/RESTfulSwarm/%s/%s' % (job_name, container_name)
                    os.mkdir(path=volume_dir)
                    self.run_container(self.storage[container_name])
                elif msg_type == 'update':
                    new_info = json.loads(' '.join(msg[1:]))
                    container_name = new_info['container_name']
                    cpuset_cpus = new_info['cpuset_cpus']
                    mem_limit = new_info['mem_limit']
                    docker.update_container(self.docker_client, container_name=container_name,
                                            cpuset_cpus=cpuset_cpus, mem_limit=mem_limit)
                    self.logger.info('Updated cpuset_cpus to %s, mem_limits to %s' % (cpuset_cpus, mem_limit))
                elif msg_type == 'leave':
                    docker.leave_swarm(self.docker_client)
                    self.logger.info('Leave Swarm environment.')
            except Exception as ex:
                self.logger.error(ex)

    def listen_worker_message(self):
        lm_controller = LiveMigration(logger=self.logger, docker_client=self.docker_client, storage=self.storage)
        lm_controller.not_migrate(SystemConstants.WORKER_PORT)

    def join_swarm(self, remote_address, join_token):
        docker.join_swarm(self.docker_client, join_token, remote_address)
        self.logger.info('Worker node join the Swarm environment.')

    def delete_old_container(self, name):
        if docker.check_container(self.docker_client, name):
            self.logger.info('Old container %s exists, deleting old container.' % name)
            container = docker.get_container(self.docker_client, name)
            docker.delete_container(container)

    def pull_image(self, image):
        if docker.check_image(self.docker_client, image) is False:
            self.logger.info('Image doesn\'t exist, pulling image.')
            docker.pull_image(self.docker_client, image)
        else:
            self.logger.info('Image already exists.')

    def run_container(self, container_info):
        container_name = container_info['container_name']
        image_name = container_info['image']
        network = container_info['network']
        command = container_info['command']
        cpuset_cpus = container_info['cpuset_cpus']
        mem_limit = container_info['mem_limit']
        detach = container_info['detach']
        ports = container_info['ports']
        volumes = container_info['volumes']
        environment = container_info['environment']
        container = docker.run_container(self.docker_client,
                                         image=image_name,
                                         name=container_name,
                                         detach=detach,
                                         network=network,
                                         command=command,
                                         cpuset_cpus=cpuset_cpus,
                                         mem_limit=mem_limit,
                                         ports=ports,
                                         volumes=volumes,
                                         environment=environment)
        self.logger.info('Container %s is running.' % container_name)
        return container

    def controller(self):
        manager_monitor_thr = threading.Thread(target=self.listen_manager_msg(), args=())
        peer_monitor_thr = threading.Thread(target=self.listen_worker_message(), args=())
        container_monitor_thr = threading.Thread(target=self.monitor,
                                                 args=(self.dis_address, self.task_monitor_frequency,))
        container_monitor_thr.daemon = True
        manager_monitor_thr.daemon = True
        peer_monitor_thr.daemon = True

        container_monitor_thr.start()
        manager_monitor_thr.start()
        peer_monitor_thr.start()

    def request_join_swarm(self):
        url = 'http://' + self.gm_address + ':5000/RESTfulSwarm/GM/request_join'
        json_info = {
            'hostname': self.hostname,
            'address': self.host_address,
            'CPUs': utl.get_total_cores(),
            'MemFree': utl.get_total_mem()
        }

        response = requests.post(url=url, json=json_info)

        # configure nfs
        if response.status_code == 200:
            # mount to the directory on nfs host server(GlobalManager)
            cmd = 'sudo mount %s:/var/nfs/RESTfulSwarm /nfs/RESTfulSwarm' % self.gm_address
            os.system(cmd)

    def request_leave_swarm(self):
        url = 'http://' + self.gm_address + ':5000/RESTfulSwarm/GM/request_leave'
        print(requests.post(url=url, json={'hostname': self.hostname}).content)

    @staticmethod
    def main(worker_init):
        # parser = argparse.ArgumentParser()
        # parser.add_argument('--GM', type=str, help='Global Manager IP address.')
        # parser.add_argument('--worker', type=str, help='Self IP address')
        # parser.add_argument('--discovery', type=str, help='Discovery server address.')
        # parser.add_argument('-f', '--frequency', type=int, default=20, help='Worker node task monitor frequency (s).')
        # args = parser.parse_args()
        # gm_address = args.GM
        # worker_address = args.worker
        # dis_address = args.discovery
        # frequency = args.frequency

        os.chdir('/home/%s/RESTfulSwarm/Worker' % utl.get_username())

        with open(worker_init) as f:
            data = json.load(f)
        gm_address = data['gm_address']
        worker_address = data['worker_address']
        dis_address = data['dis_address']
        frequency = data['frequency']

        worker = Worker(gm_address, worker_address, dis_address, frequency)

        worker.controller()
        worker.request_join_swarm()
        while True:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--file', type=str, default='Worker1Init.json', help='Worker node init json file path.')
    args = parser.parse_args()
    worker_init_json = args.file

    pro = multiprocessing.Process(
        name='Worker',
        target=Worker.main,
        args=(worker_init_json, )
    )
    pro.daemon = True
    pro.start()
    pro.join()