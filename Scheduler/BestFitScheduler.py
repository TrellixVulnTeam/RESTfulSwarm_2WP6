#!/usr/bin/env /usr/local/bin/python
# encoding: utf-8
# Author: Zhuangwei Kang

from Scheduler.Scheduler import Scheduler


class BestFitScheduler(Scheduler):
    def __init__(self, db, workers_col_name, worker_resource_col_name):
        super(BestFitScheduler, self).__init__(db, workers_col_name, worker_resource_col_name)

    def cores_scheduling_algorithm(self, core_requests, free_cores):
        req_cores = []
        for item in core_requests:
            req_cores.extend(list(item[1].values()))
        self.best_fit(req_cores, free_cores)

    def best_fit(self, requested_resources, free_resources):
        '''
        Best fit algorithm for scheduling resources
        :param requested_resources: a list of requested resources
        :param free_resources: a list of free resources
        :return: A list of tuples, best fit result [($request_index, $resource_index)]
        '''
        result = []
        for j, req in enumerate(requested_resources):
            temp = []
            for index, res in enumerate(free_resources[:]):
                if res >= req:
                    temp.append((index, res - req))
            if len(temp) > 0:
                min_index = temp[0][0]
                min_val = temp[0][1]
                for i in range(len(temp)):
                    if temp[i][1] < min_val:
                        min_index = temp[i][0]
                        min_val = temp[i][1]
                        free_resources[min_index] -= req
                result.append((j, min_index))
            else:
                # free resources are not enough
                result.append((j, -1))
        return result