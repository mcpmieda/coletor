"""Python-only synthetic QA fixture; never included in the portable application."""
class SyntheticAccess:
    def run(self, work):
        return work()

    def status(self):
        return {"authenticated": True, "authorized": True}

    def open_login(self):
        return None

    def logout(self):
        return None
