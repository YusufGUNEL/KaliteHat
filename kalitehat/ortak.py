"""Modüllerin paylaştığı küçük parçalar."""
from datetime import date, datetime


class KuralHatasi(Exception):
    """Bir kalite kuralı ihlal edildi. Mesaj doğrudan kullanıcıya gösterilir."""


def simdi() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def bugun() -> str:
    return date.today().isoformat()
