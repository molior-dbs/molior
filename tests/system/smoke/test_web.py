"""Web UI smoke tests with selenium and headless chromium: login and the main pages render."""
import os

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from moliortest import MOLIOR_URL, ADMIN_PASSWORD

RESULTS = os.environ.get("RESULTS_DIR", "/tmp/results")


@pytest.fixture
def browser(request):
    options = webdriver.ChromeOptions()
    options.binary_location = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
    for arg in ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1400,1000"]:
        options.add_argument(arg)
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    driver = webdriver.Chrome(service=Service(os.environ.get("CHROMEDRIVER", "/usr/bin/chromedriver")), options=options)
    driver.implicitly_wait(0)
    yield driver
    failed = getattr(request.node, "rep_call", None) is not None and request.node.rep_call.failed
    if failed:
        os.makedirs(RESULTS, exist_ok=True)
        driver.save_screenshot(os.path.join(RESULTS, f"{request.node.name}.png"))
    driver.quit()


def wait(driver, condition, timeout=20):
    return WebDriverWait(driver, timeout).until(condition)


def login(driver, username="admin", password=ADMIN_PASSWORD):
    driver.get(MOLIOR_URL + "/login")
    wait(driver, EC.visibility_of_element_located((By.ID, "username"))).send_keys(username)
    driver.find_element(By.ID, "password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
    wait(driver, EC.url_contains("/builds"))


def severe_errors(driver):
    return [e["message"] for e in driver.get_log("browser") if e["level"] == "SEVERE"]


def test_login_page(browser):
    browser.get(MOLIOR_URL + "/")
    wait(browser, EC.url_contains("/login"))
    assert browser.find_element(By.ID, "username").is_displayed()


def test_login_wrong_password_shows_error(browser):
    browser.get(MOLIOR_URL + "/login")
    wait(browser, EC.visibility_of_element_located((By.ID, "username"))).send_keys("admin")
    browser.find_element(By.ID, "password").send_keys("wrong")
    browser.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
    wait(browser, EC.visibility_of_element_located((By.CSS_SELECTOR, ".alert-danger")))
    assert "/login" in browser.current_url


@pytest.mark.parametrize("path", ["/builds", "/projects", "/mirrors", "/repos", "/users", "/tokens", "/about", "/admin"])
def test_page_renders(browser, path):
    login(browser)
    browser.get(MOLIOR_URL + path)
    wait(browser, EC.presence_of_element_located((By.CSS_SELECTOR, "h1, h2, table")))
    assert path in browser.current_url
    assert severe_errors(browser) == []


def test_project_appears_in_list(browser, admin, unique):
    project = unique("webproj")
    assert admin.post("/api/projects", json={"name": project}).status_code == 200
    login(browser)
    browser.get(MOLIOR_URL + "/projects")
    wait(browser, EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{project}')]")))
