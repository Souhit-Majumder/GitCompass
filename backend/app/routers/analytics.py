"""
Analytics router.

Provides endpoints for accessing aggregated Git history analytics,
such as churn rates and contributor ownership scores.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel

from app.dependencies import CurrentUser, UserDB

logger = logging.getLogger("gitcompass.routers.analytics")

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class HotspotResponse(BaseModel):
    file_path: str
    commits_count: int
    total_insertions: int
    total_deletions: int
    authors: List[str]
    is_deleted: bool


class TemporalCouplingResponse(BaseModel):
    file_a: str
    file_b: str
    co_changes: int
    coupling_percentage: float


@router.get("/{repo_id}/hotspots", response_model=List[HotspotResponse])
async def get_repository_hotspots(
    repo_id: str, 
    user: CurrentUser, 
    db: UserDB,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    commit_type: Optional[str] = Query(None)
):
    """Get the hotspot analytics (churn & contributors) for a repository.

    Aggregates file modifications in Python by paginating through file_diffs.
    This bypasses PostgREST schema cache and RPC signature mismatch issues.
    """
    try:
        # Check if repo exists and belongs to user
        repo = db.table("repositories").select("id").eq("id", repo_id).execute()
        if not repo.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository {repo_id} not found",
            )

        hotspots_map = {}
        page_size = 1000
        
        # Paginate to fetch all file diffs for this repo
        for offset in range(0, 100000, page_size):
            query = db.table("file_diffs").select(
                "file_path, insertions, deletions, is_deleted, commits!inner(author_name, committed_at, commit_type)"
            ).eq("repo_id", repo_id)
            
            if start_date:
                query = query.gte("commits.committed_at", start_date)
            if end_date:
                query = query.lte("commits.committed_at", end_date)
            if commit_type:
                query = query.eq("commits.commit_type", commit_type)

            res = query.range(offset, offset + page_size - 1).execute()
            
            if not res.data:
                break
                
            for row in res.data:
                path = row["file_path"]
                if path not in hotspots_map:
                    hotspots_map[path] = {
                        "file_path": path,
                        "commits_count": 0,
                        "total_insertions": 0,
                        "total_deletions": 0,
                        "authors": set(),
                        "is_deleted": row.get("is_deleted", False)
                    }
                
                hotspot = hotspots_map[path]
                hotspot["commits_count"] += 1
                hotspot["total_insertions"] += row.get("insertions", 0)
                hotspot["total_deletions"] += row.get("deletions", 0)
                
                commit_data = row.get("commits")
                if commit_data and commit_data.get("author_name"):
                    hotspot["authors"].add(commit_data["author_name"])

        # Convert to list and sort by churn
        results = []
        for path, data in hotspots_map.items():
            data["authors"] = list(data["authors"])
            results.append(data)
            
        results.sort(key=lambda x: x["commits_count"], reverse=True)
        return results

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to fetch hotspots for repo %s: %s", repo_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error fetching hotspots: {exc}",
        )


@router.get("/{repo_id}/coupling", response_model=List[TemporalCouplingResponse])
async def get_temporal_coupling(
    repo_id: str, 
    user: CurrentUser, 
    db: UserDB,
    file_path: Optional[str] = Query(None, description="Filter couplings for a specific file")
):
    """Get pre-calculated temporal coupling matrix for a repository.
    
    If file_path is provided, returns only couplings associated with that file.
    """
    try:
        # Check if repo belongs to user
        repo = db.table("repositories").select("id").eq("id", repo_id).execute()
        if not repo.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository {repo_id} not found",
            )

        query = db.table("temporal_coupling").select("file_a, file_b, co_changes, coupling_percentage").eq("repo_id", repo_id)
        
        if file_path:
            # We must query both file_a and file_b since the relationship is stored alphabetically
            query = query.or_(f"file_a.eq.{file_path},file_b.eq.{file_path}")
            
        res = query.order("coupling_percentage", desc=True).limit(500).execute()
        
        return res.data or []

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to fetch temporal coupling for repo %s: %s", repo_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error fetching coupling: {exc}",
        )
