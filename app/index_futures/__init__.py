"""Official China index-futures market data and research-only paper strategy."""

from app.index_futures.service import BasisUpdateResult, update_basis_snapshots

__all__ = ["BasisUpdateResult", "update_basis_snapshots"]
