RESTfulSwarm
============
An application for deploying docker containers in Swarm environment.
![](http://blog.pridybailo.com/wp-content/uploads/sites/2/2015/01/swar-q.png)
## [Environment(Prerequisites)](https://github.com/doc-vu/RESTfulSwarm/blob/master/dependences.sh)
* Ubuntu 16.04
* Python3
* Docker 17.03 (with experimental feature)
* CRIU
* Flask
* Pyzmq
* Swagger
```Bash
./dependences.sh
```
## Architecture
![](./Architecture.jpg)
### Job statechart
![](./JobState.jpg)
### FrontEnd Swagger Interface
![](./FrontEnd.PNG)
### GlobalManager Swagger Interface
![](./GlobalManager.PNG)
### MongoDB Interface
![](./WorkersInfo.JPG)
![](./JobInfo.JPG)
![](./WorkersResourceInfo.JPG)
