"""Amazon Selling Partner API adapter using LWA and AWS SigV4."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from .base import AdapterError, PlatformAdapter
from ..models import UniversalProduct

ENDPOINTS = {
    "na": ("https://sellingpartnerapi-na.amazon.com", "us-east-1"),
    "eu": ("https://sellingpartnerapi-eu.amazon.com", "eu-west-1"),
    "fe": ("https://sellingpartnerapi-fe.amazon.com", "us-west-2"),
}


class AmazonSPAPIAdapter(PlatformAdapter):
    platform = "amazon"

    def __init__(self, credentials: dict[str, Any]) -> None:
        super().__init__(credentials)
        self.c = credentials
        required = ("lwa_client_id", "lwa_client_secret", "lwa_refresh_token",
                    "aws_access_key", "aws_secret_key", "marketplace_id", "seller_id")
        missing = [key for key in required if not credentials.get(key)]
        if missing:
            raise AdapterError("Amazon configuration is incomplete: " + ", ".join(missing))
        self.endpoint, self.signing_region = ENDPOINTS.get(str(credentials.get("region", "na")).lower(), ENDPOINTS["na"])
        self._lwa_token = ""
        self._token_expires_at = 0.0

    def _access_token(self) -> str:
        if self._lwa_token and time.monotonic() < self._token_expires_at:
            return self._lwa_token
        required = ("lwa_client_id", "lwa_client_secret", "lwa_refresh_token")
        if any(not self.c.get(key) for key in required):
            raise AdapterError("Amazon requires LWA client ID, client secret, and refresh token")
        response = requests.post("https://api.amazon.com/auth/o2/token", data={
            "grant_type": "refresh_token", "refresh_token": self.c["lwa_refresh_token"],
            "client_id": self.c["lwa_client_id"], "client_secret": self.c["lwa_client_secret"],
        }, timeout=30)
        result = self.check(response)
        self._lwa_token = str(result.get("access_token", ""))
        self._token_expires_at = time.monotonic() + max(60, int(result.get("expires_in", 3600)) - 60)
        if not self._lwa_token:
            raise AdapterError("Amazon LWA did not return an access token")
        return self._lwa_token

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                 body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.c.get("aws_access_key") or not self.c.get("aws_secret_key"):
            raise AdapterError("Amazon requires AWS access key and secret for SP-API SigV4 signing")
        access_key, secret_key = self.c["aws_access_key"], self.c["aws_secret_key"]
        session_token = self.c.get("aws_session_token", "")
        role_arn = str(self.c.get("role_arn", "")).strip()
        if role_arn:
            sts = boto3.client("sts", aws_access_key_id=access_key, aws_secret_access_key=secret_key,
                               aws_session_token=session_token or None, region_name=self.signing_region)
            assumed = sts.assume_role(RoleArn=role_arn, RoleSessionName="OmniStoreDesktop")
            creds = assumed["Credentials"]
            access_key, secret_key, session_token = creds["AccessKeyId"], creds["SecretAccessKey"], creds["SessionToken"]
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None}, doseq=True)
        url = f"{self.endpoint}{path}" + (f"?{query}" if query else "")
        payload = json.dumps(body, separators=(",", ":")) if body is not None else None
        headers = {"host": self.endpoint.split("//", 1)[1], "x-amz-access-token": self._access_token(),
                   "content-type": "application/json"}
        request = AWSRequest(method=method.upper(), url=url, data=payload, headers=headers)
        credentials = Credentials(access_key, secret_key, session_token or None)
        SigV4Auth(credentials, "execute-api", self.signing_region).add_auth(request)
        prepared = request.prepare()
        response = requests.request(prepared.method, prepared.url, data=prepared.body,
                                    headers=dict(prepared.headers), timeout=40)
        return self.check(response)

    def create_product(self, product: UniversalProduct) -> dict[str, Any]:
        seller = str(self.c.get("seller_id", ""))
        marketplace = str(self.c.get("marketplace_id", ""))
        if not seller or not marketplace or not product.sku:
            raise AdapterError("Amazon product listing requires seller ID, marketplace ID, and SKU")
        attributes: dict[str, Any] = {
            "item_name": [{"value": product.title, "language_tag": "en_US", "marketplace_id": marketplace}],
            "brand": [{"value": product.vendor or "Generic", "marketplace_id": marketplace}],
            "product_description": [{"value": product.description, "language_tag": "en_US", "marketplace_id": marketplace}],
            "purchasable_offer": [{"currency": product.currency, "our_price": [{"schedule": [{"value_with_tax": float(product.price)}]}], "marketplace_id": marketplace}],
            "fulfillment_availability": [{"fulfillment_channel_code": "DEFAULT", "quantity": product.inventory_quantity}],
        }
        if product.image_urls:
            attributes["main_product_image_locator"] = [{"media_location": product.image_urls[0], "marketplace_id": marketplace}]
        if product.tags:
            attributes["generic_keyword"] = [{"value": " ".join(product.tags), "marketplace_id": marketplace}]
        path = f"/listings/2021-08-01/items/{seller}/{product.sku}"
        return self._request("PUT", path, params={"marketplaceIds": marketplace, "issueLocale": "en_US"},
                             body={"productType": product.product_type.upper().replace(" ", "_"),
                                   "requirements": "LISTING", "attributes": attributes})

    def fetch_orders(self, **kwargs: Any) -> list[dict[str, Any]]:
        marketplace = str(self.c.get("marketplace_id", ""))
        if not marketplace:
            raise AdapterError("Amazon polling requires a marketplace ID")
        result = self._request("GET", "/orders/v0/orders", params={
            "MarketplaceIds": marketplace,
            "CreatedAfter": kwargs.get("created_after") or kwargs.get("created_at_min") or
                            (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
        })
        return result.get("payload", {}).get("Orders", [])

    def update_inventory(self, product_id: str, quantity: int, **kwargs: Any) -> dict[str, Any]:
        seller = str(self.c.get("seller_id", ""))
        marketplace = str(self.c.get("marketplace_id", ""))
        if not seller or not marketplace:
            raise AdapterError("Amazon inventory update requires seller ID and marketplace ID")
        sku = str(kwargs.get("sku") or product_id)
        return self._request("PATCH", f"/listings/2021-08-01/items/{seller}/{sku}",
                             params={"marketplaceIds": marketplace}, body={"productType": "PRODUCT", "patches": [{
                                 "op": "replace", "path": "/attributes/fulfillment_availability",
                                 "value": [{"fulfillment_channel_code": "DEFAULT", "quantity": max(0, int(quantity))}],
                             }]})
