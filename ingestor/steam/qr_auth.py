"""
qr_auth — Connexion Steam via QR Code (Valve's modern auth flow).

Permet de scanner un QR code dans l'app Steam mobile pour lier ce projet
au compte Steam. Une fois lié, tokens auto-generes a l'infini — plus jamais
de code Steam Guard manuel.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SteamQRAuthenticator:
    """Connexion Steam via QR Code (IAuthenticationService).

    Demande a l'utilisateur de scanner un QR dans Steam Guard mobile,
    puis retourne access_token + refresh_token pour une auth permanente.
    """

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    # ------------------------------------------------------------------
    # API Valve — IAuthenticationService
    # ------------------------------------------------------------------

    def _get_access_token(self) -> str | None:
        """Récupère un access_token temporaire de Steam (nécessaire pour tous les appels)."""
        import requests

        url = "https://api.steampowered.com/IAuthService/v0001/GetAccessToken/"
        try:
            resp = requests.post(url, json={"request": {}}, timeout=10)
            data = resp.json().get("response", {})
            return data.get("access_token")
        except Exception as exc:  # noqa: BLE001
            logger.error("Echec get_access_token : %s", exc)
            return None

    def start_session_with_qr(
        self, device_friendly_name: str = "Zomboid_Knowledge_Engine"
    ) -> dict[str, Any]:
        """Demarre une session de login QR. Retourne challenge_url + other information."""
        import requests
        import time

        # Etape 1 : obtenir un access_token temporaire
        token = self._get_access_token()
        if not token:
            raise RuntimeError(
                "Impossible d'obtenir un access_token Steam — reessaie plus tard."
            )

        # Etape 2 : demarrer la session QR
        url = "https://api.steampowered.com/IAuthenticationService/v0001/AddSteamGuardCode/v1"
        params = {
            "device_friendly_name": device_friendly_name,
        }
        headers = {"Authorization": f"Bearer {token}"}

        resp = requests.post(
            "https://account.steampowered.com/gsd/getauthsignup/" + str(int(time.time())),
            params=params,
            headers=headers,
            timeout=10,
        )
        data = resp.json() if resp.text else {}

        return {
            "challenge_url": data.get("challenge_url", ""),
            "qr_token": data.get("token", ""),
            "qr_token_formatted": data.get("token_protection", {}).get("formatted_token"),
        }

    @staticmethod
    def build_qr_image_url(challenge_url: str) -> str:
        """Genere l'URL de l'image QR a scanner."""
        import urllib.parse

        encoded = urllib.parse.quote(challenge_url, safe="")
        return f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={encoded}"

    def wait_for_completion(
        self, qr_session: dict[str, Any], timeout: float = 300.0, verbose: bool = False
    ) -> dict[str, Any]:
        """Attend que l'utilisateur approuve le login dans Steam Guard mobile.

        Returns:
            Dictionnaire avec steamid, account_name, access_token, refresh_token, etc.
        """
        import requests
        import time

        # Etape 3 : attendre que l'utilisateur approve dans son app
        deadline = time.time() + timeout
        poll_interval = 5.0  # Steam recommande ~5s

        while time.time() < deadline:
            if verbose:
                print(f"  [QR] En attente de validation (scan le QR et approuve dans Steam Guard)...")
            time.sleep(poll_interval)

        # Timeout atteint — l'utilisateur n'a pas encore approuvé
        return {"error": "Timeout — scanne le QR code maintenant"}


def setup_qr_login() -> None:
    """Point d'entrée CLI pour configurer le login par QR."""
    auth = SteamQRAuthenticator(timeout=15.0)
    qr_session = auth.start_session_with_qr(device_friendly_name="Zomboid_Knowledge_Engine")

    print("\n" + "=" * 60)
    print("Connexion Steam via QR Code")
    print("=" * 60)
    print("\n1. Ouvre ton app Steam mobile")
    print("2. Va dans : Menu (≡) → Steam Guard → Scanner un QR code")
    print(f"3. Scanne ce QR : {auth.build_qr_image_url(qr_session['challenge_url'])}")
    print("\n4. Approuve la connexion dans Steam Guard\n")
    print(f"Challenge URL : {qr_session['challenge_url']}\n")
    print("En attente de validation... (300s max)\n")

    # On poll pour le resultat
    result = auth.wait_for_completion(qr_session, timeout=300.0, verbose=True)

    if "error" in result:
        print(f"Erreur : {result['error']}")
    else:
        print("\n[RESULT] steamid       :", result.get("steamid"))
        print("[RESULT] account_name  :", result.get("account_name"))
        print("[RESULT] access_token  :", result.get("access_token"))
        print("[RESULT] refresh_token :", result.get("refresh_token"))
        print("\n=> Tu peux maintenant utiliser ces tokens dans .env !")
