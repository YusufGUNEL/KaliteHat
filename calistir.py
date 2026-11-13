from pathlib import Path

from kalitehat import create_app

if __name__ == "__main__":
    if not (Path(__file__).parent / "veri" / "kalitehat.db").exists():
        import ornek_veri

        ornek_veri.main()
    create_app().run(port=5050, debug=False)
