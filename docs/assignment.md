# P1: Kubernetes

---

### Background
Much to people's surprise, the fortune cookie is not a Chinese invention, but an American one. Its exact origin is unclear, however, it most likely originated from cookies made by Japanese immigrants to the United States in the late 19th or early 20th century. It is a crisp and sugary cookie wafer with a piece of paper inside, a "fortune", usually an aphorism, or a vague prophecy. It is often served as a dessert in Chinese restaurants in Western countries.

### Problem formulation
In this project you will get a chance to offer people an infinite amount of fortune cookies by just clicking a button. You will use Kubernetes to host a website that can return a fortune cookie upon request. You can store these cookies in memory, in a file or fetch them from the Internet. The website can be a simple HTML page, some CSS styling and a bit of JavaScript. You must also design, implement and use the Bully algorithm to elect a leader pod, that would host the website. Should the leader pod fail, a new must be elected via the algorithm. You are free to design your solution in Kubernetes however you want, but it should at least contain:

- A deployment specification that supports multiple pods.
- An active Bully algorithm that elects a new leader when the current fails.
- A website with some visualization of the cookie text and a way to get more (see fig. 1).
Your report should explain your design decisions and how you have implemented your solution. You must also make the following experiments:

- Run a load test towards your Kubernetes cluster and note down the response times. You can use PowerShell or NodeJS to make a simple loop that sends a lot of HTTP requests to your endpoint rapidly.
- Simulate pod failure by shutting down the leader pod and document how the leader election algorithm now elects a new leader. How long does it take to find a new leader? Do the users notice any lag?
You might find Headless Services and StatefulSets useful in this project (see
[https://kubernetes.io/docs/concepts/services-networking/service/#headless-services.](https://kubernetes.io/docs/concepts/services-networking/service/#headless-services.)
and
[https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
respectively).

![](https://brightspace.au.dk/content/enforced/219533-LR60464/Pictures/fortune_cookie_project.png)

Figure 1: How your fortune cookie website could look.

### Getting started
We have made a repository with some code to get you started:
[https://github.com/thecml/bully-in-kubernetes](https://github.com/thecml/bully-in-kubernetes)

In order to make the Bully algorithm run in Kubernetes pods instead of threads, we need a way for them to communicate with each other. One way to do this is creating API’s (endpoints) that you can call using a HTTP request. You can create these endpoints in Python, JavaScript, C# or another language. We recommend you use Python, if you already have experience with that language. For the pods to discover each other, we can create a headless service and make a nslookup to it to get the pods backing that service. When we have the other pod IP’s, we interact with them by sending them HTTP requests like GET, POST, PUT and DELETE.

This repository contains some basic code to set-up a deployment, a service and Python source code. The code creates an API using the ”aiohttp” library ([https://docs.aiohttp.org/en/stable/index.html](https://docs.aiohttp.org/en/stable/index.html)), which exposes a set of actions on the pod. This is an asynchronous alternative to Flask, another web-server ([https://flask.palletsprojects.com/en/2.2.x/](https://flask.palletsprojects.com/en/2.2.x/)).

It then runs a periodic task that queries the headless service for pods, then sends a HTTP GET request to each pod using the "request" library to get their ID’s, and then saves the ID’s in a dictionary. Each pod knows it own IP from an environment variable (see deployment.yaml). The code currently sends synchronous HTTP requests. If you want to use aiohttp to send asynchrnous requests, see: [https://docs.aiohttp.org/en/stable/client_quickstart.html.](https://docs.aiohttp.org/en/stable/client_quickstart.html)

If you want to use DockerHub, change the deployment.yaml file to use DockerHub instead of local images and set it to pull a new image every time. See more here:
[https://kubernetes.io/docs/concepts/containers/images/](https://kubernetes.io/docs/concepts/containers/images/).

If you don’t want to use Dockerhub for your images and instead store them locally (faster), see the following post:
[https://stackoverflow.com/a/48999680](https://stackoverflow.com/a/48999680)

Lastly, Python has a Kubernetes client, that can make some things easier, like communicating with the Kubernetes API: [https://github.com/kubernetes-client/python](https://github.com/kubernetes-client/python)

This you how you can run it all:
$ docker build -t bully-app .
$ kubectl apply -f .\ k8s\headless-service.yaml
$ kubectl apply -f .\ k8s\deployment.yaml
