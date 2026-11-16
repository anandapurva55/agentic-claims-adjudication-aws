"""Cognito's sign in page, styled to match the app. The settings are the ones exported from a pool where the design was checked in a browser, and the two images are
the page background (the app's example review card on the app's own dark ground) and the wordmark. The whole page is dark, so only the dark mode assets are set."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from aws_cdk import aws_cognito as cognito
from constructs import Construct

HERE = Path(__file__).parent / "branding"


def _asset(category: str, filename: str) -> cognito.CfnManagedLoginBranding.AssetTypeProperty:
    return cognito.CfnManagedLoginBranding.AssetTypeProperty(
        category=category, color_mode="DARK", extension="PNG", bytes=base64.b64encode((HERE / filename).read_bytes()).decode())


def style_sign_in_page(scope: Construct, pool: cognito.UserPool, client: cognito.UserPoolClient) -> cognito.CfnManagedLoginBranding:
    """Needs the pool's domain to use managed login (the newer sign in page) and the Essentials feature plan, both set where the pool is created."""
    return cognito.CfnManagedLoginBranding(
        scope, "SignInBranding", user_pool_id=pool.user_pool_id, client_id=client.user_pool_client_id, use_cognito_provided_values=False,
        settings=json.loads((HERE / "settings.json").read_text()),
        assets=[_asset("PAGE_BACKGROUND", "page_background.png"), _asset("FORM_LOGO", "form_logo.png")])
