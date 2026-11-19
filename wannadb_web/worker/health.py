"""Publish worker availability from the Celery consumer event loop."""

from uuid import uuid4

from celery import bootsteps
from redis.exceptions import RedisError

from wannadb_web.queue_health import (
    HEARTBEAT_INTERVAL, connect_monitor, publish_heartbeat, remove_heartbeat,
)


class QueueHeartbeat(bootsteps.StartStopStep):
    """Refresh queue leases during idle and busy prefork worker operation."""

    requires = ("celery.worker.consumer.tasks:Tasks",)

    def __init__(self, consumer, **kwargs):
        super().__init__(consumer, **kwargs)
        self.consumer_id = uuid4().hex
        self.timer = None

    def start(self, consumer):
        self.timer = consumer.timer.call_repeatedly(HEARTBEAT_INTERVAL, self.publish, (consumer,))

    def publish(self, consumer):
        queues = []
        if consumer.connection and consumer.connection.connected and consumer.task_consumer:
            queues = [queue.name for queue in consumer.task_consumer.queues
                      if consumer.task_consumer.consuming_from(queue.name)]
        try:
            with connect_monitor() as redis:
                publish_heartbeat(redis, self.consumer_id, queues)
        except RedisError:
            # A failed refresh expires naturally. Celery owns broker reconnection.
            pass

    def stop(self, consumer):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        try:
            with connect_monitor() as redis:
                remove_heartbeat(redis, self.consumer_id)
        except RedisError:
            pass

    shutdown = stop
