"""GET/POST /api/roots, DELETE /api/roots/{id}.

S1 stub: returns/echoes fixture data. No real consent flow, filesystem
watching, or persistence to index_roots yet -- see worker/worker.py.
"""
from __future__ import annotations

from fastapi import APIRouter

from api.fixtures import FIXTURE_ROOT
from api.schemas import (
    CreateRootRequest,
    CreateRootResponse,
    DeleteRootResponse,
    IndexRoot,
    ListRootsResponse,
)

router = APIRouter(prefix="/api/roots", tags=["roots"])


@router.get("", response_model=ListRootsResponse)
def list_roots() -> ListRootsResponse:
    return ListRootsResponse(roots=[FIXTURE_ROOT])


@router.post("", response_model=CreateRootResponse, status_code=201)
def create_root(req: CreateRootRequest) -> CreateRootResponse:
    new_root = IndexRoot(
        id=FIXTURE_ROOT.id + 1,
        path=req.path,
        enabled=True,
        exclude_patterns=req.exclude_patterns,
        granted_at=None,
        paused=False,
    )
    return CreateRootResponse(root=new_root)


@router.delete("/{root_id}", response_model=DeleteRootResponse)
def delete_root(root_id: int) -> DeleteRootResponse:
    return DeleteRootResponse(id=root_id, deleted=True)
