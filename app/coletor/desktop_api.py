"""Desktop bridge for narrowly scoped non-secret local settings."""
from .local_settings import LocalSettings, default_settings
from .service import PreviewApi


class DesktopApi(PreviewApi):
    def __init__(self, settings_directory=None):
        self._settings = LocalSettings(settings_directory)

    def get_local_settings(self):
        try:
            return self._settings.read()
        except OSError:
            return {"settings": default_settings(),
                    "notice": "Não foi possível carregar as configurações. Você pode ajustar nesta sessão."}

    def _save(self, field, value):
        try:
            return {"settings": self._settings.update(field, value)}
        except (OSError, ValueError, TypeError, RecursionError):
            return {"error": "Não foi possível salvar neste computador. Suas alterações continuam na tela."}

    def save_schedule(self, schedule):
        return self._save("schedule", schedule)

    def save_theme(self, theme):
        return self._save("theme", theme)

    def save_fox(self, fox):
        return self._save("fox", fox)

