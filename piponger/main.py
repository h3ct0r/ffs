#! /usr/bin/python3
# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
import logging.handlers
from flask_httpauth import HTTPBasicAuth
import socket
import celery
from celery.schedules import crontab

from tasks.common_tasks import report_to_master
from tasks.master_tasks import remove_old_nodes


# define celery object and parameters
def make_celery(flask_app):
    celery_obj = celery.Celery(
        flask_app.import_name,
        broker=flask_app.config['CELERY_BROKER_URL'],
        backend=flask_app.config['CELERY_RESULT_BACKEND'])
    celery_obj.conf.update(flask_app.config)
    task_base = celery_obj.Task

    class ContextTask(task_base):
        abstract = True

        def __call__(self, *args, **kwargs):
            with flask_app.app_context():
                return task_base.__call__(self, *args, **kwargs)

    celery_obj.Task = ContextTask
    return celery_obj


# log config
syslog = logging.handlers.SysLogHandler(address='/dev/log')
syslog.setLevel(logging.DEBUG)
syslog.setFormatter(logging.Formatter('piponger: %(levelname)s - %(message)s'))
logger = logging.getLogger('piponger')
logger.setLevel(logging.DEBUG)
logger.addHandler(syslog)

# Flask config
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config.from_object(__name__)
app.config.from_pyfile('config_default.cfg')
app.config.from_envvar('FLASKR_SETTINGS', silent=True)

app.config['CELERYBEAT_SCHEDULE'] = {
    'create-iteration': {
        'task': 'tasks.master_tasks.create_iteration',
        'schedule': crontab(minute="*/30"),
    },
    'report-to-master': {
        'task': 'tasks.common_tasks.report_to_master',
        'schedule': crontab(minute="*/1"),
        'args': [app.config['API_PORT'], app.config['API_PROTOCOL']]
    },
    'remove-old-nodes': {
        'task': 'tasks.master_tasks.remove_old_nodes',
        'schedule': crontab(minute="*/5"),
    }
}

make_celery(app)

auth = HTTPBasicAuth()
db = SQLAlchemy()
db.init_app(app)


@auth.get_password
def get_pw(username):
    if username.strip() == app.config['HTTP_AUTH_USER']:
        return app.config['HTTP_AUTH_PASS']
    return None


def pipong_is_pinger():
    return app.config['IS_PINGER']


def pipong_is_ponger():
    return app.config['IS_PONGER']


def pipong_is_master():
    return app.config['IS_MASTER']


def get_local_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    s.listen(1)
    port = s.getsockname()[1]
    s.close()
    return port


def get_local_ip():
    return (([
        ip for ip in socket.gethostbyname_ex(socket.gethostname())[2]
        if not ip.startswith("127.")
    ] or [[(s.connect(("8.8.8.8", 53)), s.getsockname()[0], s.close())
           for s in [socket.socket(socket.AF_INET, socket.SOCK_DGRAM)]][0][1]])
            + ["no IP found"])[0]


report_to_master.apply_async(
    args=[app.config['API_PORT'], app.config['API_PROTOCOL']], kwargs={})
remove_old_nodes.apply_async(args=[], kwargs={})