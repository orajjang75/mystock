"""A backend for the browser (Playwright) tests: a mock market whose clock the test controls.

It is never imported by ``app``. ``e2e.server:create_e2e_app`` refuses to start unless
``E2E_MODE=1`` and the database is named ``*_e2e``, so it cannot touch the development data.
"""
