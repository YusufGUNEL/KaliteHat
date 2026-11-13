"""API sözleşmesi (OpenAPI 3.0). /api/v1/openapi.json adresinden sunulur, /api-belgesi sayfası bundan üretilir."""

_HATA = {"$ref": "#/components/schemas/Hata"}

SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "KaliteHat ERP API",
        "version": "1.0.0",
        "description": "ERP ile kalite sistemi arasındaki sözleşme. İş emirleri ERP'den gelir; kalite durumu ve "
        "kalite olayları ERP'ye döner. Tüm uçlar X-API-Key başlığı ister.",
    },
    "servers": [{"url": "/api/v1"}],
    "security": [{"ApiKey": []}],
    "paths": {
        "/is-emirleri": {
            "post": {
                "summary": "ERP'den iş emri gönder",
                "description": "Tek nesne ya da liste (en fazla 500). Aynı iş emri no ikinci kez gelirse atlanır; "
                "istek güvenle tekrarlanabilir.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "oneOf": [{"$ref": "#/components/schemas/IsEmriGirdi"},
                              {"type": "array", "items": {"$ref": "#/components/schemas/IsEmriGirdi"}}]}}}},
                "responses": {
                    "201": {"description": "En az bir iş emri eklendi",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AlimSonucu"}}}},
                    "200": {"description": "Hiçbiri eklenmedi (hepsi atlandı)",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AlimSonucu"}}}},
                    "400": {"description": "Geçersiz gövde", "content": {"application/json": {"schema": _HATA}}},
                    "401": {"description": "API anahtarı yok/yanlış", "content": {"application/json": {"schema": _HATA}}},
                },
            },
            "get": {
                "summary": "İş emirlerini kalite durumlarıyla listele",
                "parameters": [
                    {"name": "durum", "in": "query", "schema": {"$ref": "#/components/schemas/Durum"}},
                    {"name": "sayfa", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "boyut", "in": "query", "schema": {"type": "integer", "default": 50, "maximum": 200}},
                ],
                "responses": {"200": {"description": "Sayfalı liste"}},
            },
        },
        "/is-emirleri/{no}": {
            "get": {
                "summary": "Bir iş emrinin kalite özeti",
                "description": "ERP sevkiyat öncesi `sevke_uygun` alanına bakar.",
                "parameters": [{"name": "no", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {
                    "200": {"description": "Kalite özeti",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/KaliteOzeti"}}}},
                    "404": {"description": "Yok", "content": {"application/json": {"schema": _HATA}}},
                },
            }
        },
        "/olaylar": {
            "get": {
                "summary": "Kalite olay akışı (pull)",
                "description": "ERP son işlediği olay_id'yi `sonra` ile verir. Aynı olaylar webhook ile push da "
                "edilebilir; her olayın `anahtar` alanı tekrar teslimde aynıdır (idempotency).",
                "parameters": [
                    {"name": "sonra", "in": "query", "schema": {"type": "integer", "default": 0}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100, "maximum": 500}},
                ],
                "responses": {"200": {"description": "Olaylar ve sonraki imleç"}},
            }
        },
    },
    "components": {
        "securitySchemes": {"ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
        "schemas": {
            "Durum": {"type": "string", "enum": ["FAI_BEKLIYOR", "URETIMDE", "KARANTINA", "ONAYLI"]},
            "IsEmriGirdi": {
                "type": "object", "required": ["is_emri_no", "parca_kodu", "lot", "adet"],
                "properties": {
                    "is_emri_no": {"type": "string", "example": "IE-2026-1070"},
                    "parca_kodu": {"type": "string", "example": "SN-50"},
                    "lot": {"type": "string", "example": "L261114-SN07"},
                    "adet": {"type": "integer", "minimum": 1, "example": 40},
                    "termin": {"type": "string", "format": "date", "example": "2026-11-28"},
                },
            },
            "AlimSonucu": {"type": "object", "properties": {
                "eklenen": {"type": "array", "items": {"type": "string"}},
                "atlanan": {"type": "array", "items": {"type": "object", "properties": {
                    "is_emri_no": {"type": "string"}, "sebep": {"type": "string"}}}},
            }},
            "KaliteOzeti": {"type": "object", "properties": {
                "is_emri_no": {"type": "string"}, "lot": {"type": "string"},
                "durum": {"$ref": "#/components/schemas/Durum"},
                "sevke_uygun": {"type": "boolean"}, "fai_onayli": {"type": "boolean"},
                "adet": {"type": "integer"}, "hurda_adet": {"type": "integer"}, "saglam_adet": {"type": "integer"},
                "acik_uygunsuzluk": {"type": "integer"},
                "son_muayene": {"type": "object", "nullable": True},
            }},
            "Olay": {"type": "object", "properties": {
                "olay_id": {"type": "integer"}, "anahtar": {"type": "string", "example": "kalitehat-olay-42"},
                "tur": {"type": "string", "enum": ["FAI_ONAYLANDI", "LOT_KARANTINAYA_ALINDI", "LOT_KARANTINADAN_CIKTI",
                                                   "HURDA_BILDIRILDI", "LOT_SEVKE_UYGUN"]},
                "is_emri_no": {"type": "string"}, "zaman": {"type": "string"}, "veri": {"type": "object"},
            }},
            "Hata": {"type": "object", "properties": {"hata": {"type": "object", "properties": {
                "kod": {"type": "string", "example": "YETKISIZ"}, "mesaj": {"type": "string"},
                "ayrinti": {}}}}},
        },
    },
}
