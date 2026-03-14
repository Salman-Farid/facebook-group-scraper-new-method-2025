from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class FacebookGroupPost:
    id: int
    post_text: Optional[str]
    phone_numbers: Optional[list[str]]
    hashtags: Optional[list[str]]
    image_urls: Optional[dict]
    post_url: Optional[str]
    post_hash: str
    scraped_at: datetime