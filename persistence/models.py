from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any


@dataclass
class NormalizedVariant:
    size: str = ""
    sku: Optional[str] = None
    style: Optional[str] = None
    ean: Optional[str] = None
    available: bool = True
    stock: int = 0
    price: Optional[float] = None
    mrp: Optional[float] = None
    url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedProduct:
    source: str  # "tata", "columbia", "adv", "tata_lux", "amazon"
    source_product_id: str
    title: str
    style: Optional[str] = None
    sku: Optional[str] = None
    ean: Optional[str] = None
    price: Optional[float] = None
    mrp: Optional[float] = None
    available: bool = True
    stock: int = 0
    image_url: Optional[str] = None
    url: Optional[str] = None
    variants: List[NormalizedVariant] = field(default_factory=list)
    offers: List[Dict[str, Any]] = field(default_factory=list)
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["variants"] = [v.to_dict() if isinstance(v, NormalizedVariant) else v for v in self.variants]
        return d

    def to_db_row(self, scraper_id: str) -> Dict[str, Any]:
        """Maps normalized product to Supabase schema."""
        return {
            "scraper_id": scraper_id,
            "source_product_id": str(self.source_product_id).strip(),
            "style": self.style.strip() if self.style else None,
            "sku": self.sku.strip() if self.sku else None,
            "ean": self.ean.strip() if self.ean else None,
            "title": self.title.strip() if self.title else "",
            "url": self.url.strip() if self.url else None,
            "image_url": self.image_url.strip() if self.image_url else None,
            "available": bool(self.available),
            "current_price": float(self.price) if self.price is not None else None,
            "current_mrp": float(self.mrp) if self.mrp is not None else None,
            "variants": [v.to_dict() if isinstance(v, NormalizedVariant) else v for v in self.variants],
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
