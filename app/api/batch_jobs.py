"""批量任务 API 端点。"""

import logging

from litestar import Controller, get, patch, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

from app.services.batch_jobs import (
    cancel_batch_job,
    create_batch_job,
    get_batch_job_detail,
    get_batch_jobs,
    pause_batch_job,
    resume_batch_job,
)

logger = logging.getLogger(__name__)


class BatchJobController(Controller):
    """批量任务管理 API。"""

    path = "/api/batch-jobs"

    @post("/")
    async def create_job(self, data: dict) -> dict:
        """POST /api/batch-jobs - 创建批量任务。"""
        document_uuids = data.get("document_uuids")
        handlers = data.get("handlers")

        if not document_uuids or not isinstance(document_uuids, list):
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="document_uuids 必须是非空列表",
            )
        if not handlers or not isinstance(handlers, list):
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="handlers 必须是非空列表",
            )

        # 验证 handler 格式
        for h in handlers:
            if not isinstance(h, dict) or "plugin_name" not in h or "handler_name" not in h:
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail="每个 handler 必须包含 plugin_name 和 handler_name",
                )

        result = await create_batch_job(document_uuids, handlers)
        return result

    @get("/")
    async def list_jobs(
        self,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict:
        """GET /api/batch-jobs - 获取任务列表。"""
        return await get_batch_jobs(status=status, page=page, limit=limit)

    @get("/{job_uuid:str}")
    async def get_job_detail(self, job_uuid: str) -> dict:
        """GET /api/batch-jobs/{uuid} - 获取任务详情。"""
        result = await get_batch_job_detail(job_uuid)
        if result is None:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail="任务不存在",
            )
        return result

    @patch("/{job_uuid:str}")
    async def control_job(self, job_uuid: str, data: dict) -> dict:
        """PATCH /api/batch-jobs/{uuid} - 控制任务（暂停/恢复/取消）。"""
        action = data.get("action")
        if action not in ("pause", "resume", "cancel"):
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="action 必须是 pause/resume/cancel",
            )

        if action == "pause":
            result = await pause_batch_job(job_uuid)
        elif action == "resume":
            result = await resume_batch_job(job_uuid)
        else:
            result = await cancel_batch_job(job_uuid)

        if "error" in result:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=result["error"],
            )
        return result
