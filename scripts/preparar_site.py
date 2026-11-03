"""Empacota a demonstração estática; nenhum arquivo de data/ entra no Pages."""

from pathlib import Path
import shutil

RAIZ = Path(__file__).resolve().parents[1]
PUBLICOS = ("index.html", "styles.css", "app.js", "demo.js", "favicon.svg")


def main() -> None:
    fonte = RAIZ / "web"
    destino = RAIZ / "_site"
    for nome in PUBLICOS:
        arquivo = fonte / nome
        if not arquivo.is_file() or arquivo.is_symlink():
            raise SystemExit(f"arquivo público ausente ou link simbólico: {nome}")
    if destino.is_symlink():
        raise SystemExit("_site não pode ser um link simbólico")
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir()
    for nome in PUBLICOS:
        shutil.copyfile(fonte / nome, destino / nome)
    (destino / ".nojekyll").touch()
    print(f"Demonstração pronta: {destino} ({len(PUBLICOS)} arquivos públicos, sem catálogo real)")


if __name__ == "__main__":
    main()
