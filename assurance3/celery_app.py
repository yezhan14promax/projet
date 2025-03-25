from celery import Celery

celery_app = Celery(
    "loan_plan_service",
    broker="redis://localhost:6379/0",  # Redis 作为消息队列
    backend="redis://localhost:6379/0"
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
)

celery_app.autodiscover_tasks(['assurance3'])
