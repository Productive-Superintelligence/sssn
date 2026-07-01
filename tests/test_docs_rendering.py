import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest


ROOT = Path(__file__).resolve().parents[1]


def chromium_executable() -> str | None:
    return (
        shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
    )


def build_docs(tmp_path: Path) -> Path:
    pytest.importorskip("mkdocs")
    site_dir = tmp_path / "site"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "--site-dir",
            str(site_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    return site_dir


def css_block(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}", css, re.S)
    assert match, f"missing CSS selector: {selector}"
    return match.group("body")


def test_docs_use_channel_protocol_framing():
    sources = {
        "README": ROOT / "README.md",
        "docs home": ROOT / "docs" / "index.md",
        "channels guide": ROOT / "docs" / "concepts" / "channels.md",
        "data-plane guide": ROOT / "docs" / "concepts" / "data-plane.md",
        "contributing": ROOT / "CONTRIBUTING.md",
        "package docstring": ROOT / "sssn" / "__init__.py",
        "package metadata": ROOT / "pyproject.toml",
        "site metadata": ROOT / "mkdocs.yml",
    }
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in sources.values()
    )

    assert "protocol and service layer for semantic channels" in combined
    assert "backing implementations" in combined
    assert re.search(r"stable\s+`Channel`\s+interface", combined)
    assert "Semantic data plane" not in combined
    assert "semantic data and communication plane" not in combined
    assert "semantic channel data plane" not in combined


def test_docs_render_mermaid_as_diagram_containers(tmp_path):
    site_dir = build_docs(tmp_path)
    html_pages = [
        (path, path.read_text(encoding="utf-8"))
        for path in sorted(site_dir.rglob("*.html"))
    ]
    diagram_pages = [
        path for path, html in html_pages if 'class="mermaid"' in html
    ]
    highlighted_pages = [
        path
        for path, html in html_pages
        if "language-mermaid" in html or "highlight-mermaid" in html
    ]

    assert diagram_pages
    assert not highlighted_pages

    for path in diagram_pages:
        html = path.read_text(encoding="utf-8")
        assert "javascripts/vendor/mermaid.min.js" in html
        assert "javascripts/mermaid-init.20260629.js" in html
        assert "cdn.jsdelivr" not in html
        assert "unpkg" not in html

    vendor_js = site_dir / "javascripts" / "vendor" / "mermaid.min.js"
    vendor_license = site_dir / "javascripts" / "vendor" / "mermaid-LICENSE.txt"
    assert vendor_js.exists()
    assert vendor_license.exists()


def test_docs_render_mermaid_svgs_in_chromium(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    chromium = chromium_executable()
    if not chromium:
        pytest.skip("Chromium executable is not available")

    site_dir = build_docs(tmp_path)
    diagram_pages = [
        path
        for path in sorted(site_dir.rglob("*.html"))
        if 'class="mermaid"' in path.read_text(encoding="utf-8")
    ]

    assert diagram_pages

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=chromium,
            headless=True,
            args=["--no-sandbox"],
        )
        for path in diagram_pages:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            console_errors = []
            page.on(
                "console",
                lambda msg: console_errors.append(msg.text)
                if msg.type in {"error", "warning"}
                else None,
            )
            page.goto(path.as_uri(), wait_until="domcontentloaded")
            page.wait_for_function(
                """
                () => {
                  const diagrams = [...document.querySelectorAll('.md-typeset .mermaid')];
                  return diagrams.length > 0 &&
                    diagrams.every((diagram) =>
                      diagram.hasAttribute('data-mermaid-source') &&
                      diagram.querySelector('svg')
                    );
                }
                """,
                timeout=5000,
            )
            assert page.evaluate(
                "() => document.querySelectorAll('[data-mermaid-error=\"true\"]').length"
            ) == 0
            assert page.evaluate(
                "() => document.querySelectorAll('code.language-mermaid, code.highlight-mermaid').length"
            ) == 0
            assert page.evaluate("() => document.body.innerText.includes('flowchart')") is False
            diagram_metrics = page.evaluate(
                """
                () => [...document.querySelectorAll(".md-typeset .mermaid")]
                  .map((diagram) => {
                  const svg = diagram.querySelector("svg");
                  const label = svg.querySelector(
                    "foreignObject span, .nodeLabel, .edgeLabel, text, tspan"
                  );
                  const labelStyle = label ? getComputedStyle(label) : null;
                  const diagramRect = diagram.getBoundingClientRect();
                  const svgRect = svg.getBoundingClientRect();
                  const shapes = [
                    ...svg.querySelectorAll(
                      "path, rect, circle, ellipse, polygon, line"
                    )
                  ].map((element) => {
                    const style = getComputedStyle(element);
                    return {
                      fill: style.fill,
                      stroke: style.stroke,
                    };
                  });
                  return {
                    diagramHeight: diagramRect.height,
                    diagramWidth: diagramRect.width,
                    labelColor: labelStyle ? labelStyle.color : "",
                    labelFill: labelStyle ? labelStyle.fill : "",
                    shapeInk: shapes.filter((shape) =>
                      [shape.fill, shape.stroke].includes("rgb(5, 5, 5)")
                    ).length,
                    source: diagram.getAttribute("data-mermaid-source") || "",
                    svgHeight: svgRect.height,
                    svgText: svg.textContent.trim(),
                    svgWidth: svgRect.width,
                  };
                })
                """
            )
            for metric in diagram_metrics:
                assert metric["source"].lstrip().startswith("flowchart")
                assert metric["diagramWidth"] > 120
                assert metric["diagramHeight"] > 80
                assert metric["svgWidth"] > 120
                assert metric["svgHeight"] > 80
                assert metric["svgText"]
                assert metric["shapeInk"] > 0
                assert "rgb(5, 5, 5)" in {
                    metric["labelColor"],
                    metric["labelFill"],
                }
            assert [
                message
                for message in console_errors
                if "Failed to load resource" not in message
            ] == []
            page.close()
        browser.close()


def test_docs_chrome_matches_light_visual_contract(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    chromium = chromium_executable()
    if not chromium:
        pytest.skip("Chromium executable is not available")

    site_dir = build_docs(tmp_path)

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=chromium,
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(
            (site_dir / "index.html").as_uri(), wait_until="domcontentloaded"
        )
        page.wait_for_selector(
            ".md-header__button.md-logo img, .md-header__button.md-logo svg"
        )
        metrics = page.evaluate(
            """
            () => {
              const inspect = (selector) => {
                const element = document.querySelector(selector);
                if (!element) {
                  return null;
                }
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return {
                  backgroundColor: style.backgroundColor,
                  boxShadow: style.boxShadow,
                  color: style.color,
                  display: style.display,
                  fontFamily: style.fontFamily,
                  fontWeight: style.fontWeight,
                  height: rect.height,
                  component: element.getAttribute("data-md-component") || "",
                  src: element.getAttribute("src") || "",
                  text: element.textContent.trim().replace(/\\s+/g, " "),
                  width: rect.width,
                };
              };
              const brandImages = [...document.querySelectorAll(".psi-brand img")]
                .map((element) => {
                  const style = getComputedStyle(element);
                  const rect = element.getBoundingClientRect();
                  return {
                    display: style.display,
                    height: rect.height,
                    src: element.getAttribute("src") || "",
                    width: rect.width,
                  };
                });
              return {
                bodyFont: getComputedStyle(document.body)
                  .getPropertyValue("--md-text-font-family")
                  .trim(),
                codeFont: getComputedStyle(document.body)
                  .getPropertyValue("--md-code-font-family")
                  .trim(),
                footer: inspect(".md-footer-meta"),
                footerMark: inspect(".psi-footer-wordmark"),
                header: inspect(".md-header"),
                headerLogo: inspect(
                  ".md-header__button.md-logo img, .md-header__button.md-logo svg"
                ),
                drawerSections: inspect(".psi-drawer-sections"),
                headerNav: inspect(".psi-header-nav"),
                headerNavLinks: [...document.querySelectorAll(".psi-header-nav__link")]
                  .map((element) => element.textContent.trim().replace(/\\s+/g, " ")),
                palette: inspect(".md-header__option[data-md-component='palette']"),
                sidebarText: document
                  .querySelector(".md-sidebar--primary .md-nav--primary > .md-nav__list")
                  ?.innerText.trim().replace(/\\s+/g, " ") || "",
                source: inspect(".md-header__source .md-source"),
                sourceRepository: document
                  .querySelector(".md-header__source .md-source__repository")
                  ?.textContent.trim().replace(/\\s+/g, " ") || "",
                tabs: inspect(".md-tabs"),
                title: inspect(".md-header__title"),
                brandImages,
              };
            }
            """
        )
        page.goto(
            (site_dir / "tutorials" / "first-channel" / "index.html").as_uri(),
            wait_until="domcontentloaded",
        )
        tutorial_sidebar = page.locator(
            ".md-sidebar--primary .md-nav--primary > .md-nav__list"
        ).inner_text()
        page.close()
        browser.close()

    assert metrics["header"]["backgroundColor"] == "rgb(255, 255, 255)"
    assert metrics["tabs"] is None
    assert metrics["footer"]["backgroundColor"] == "rgb(255, 255, 255)"
    assert metrics["header"]["color"] == "rgb(5, 5, 5)"
    assert metrics["footer"]["color"] == "rgb(5, 5, 5)"
    assert metrics["header"]["boxShadow"] == "none"
    assert metrics["title"]["fontWeight"] == "700"
    assert metrics["headerLogo"]["width"] == pytest.approx(24, abs=1)
    assert metrics["headerLogo"]["height"] == pytest.approx(24, abs=1)
    assert metrics["palette"]["width"] == pytest.approx(0, abs=1)
    assert metrics["palette"]["height"] == pytest.approx(0, abs=1)
    assert metrics["drawerSections"]["display"] == "none"
    assert metrics["headerNav"]["display"] == "flex"
    assert metrics["headerNavLinks"] == [
        "Overview",
        "Protocol",
        "Runtime",
        "Tutorials",
        "Reference",
    ]
    assert "Overview" in metrics["sidebarText"]
    assert "Getting Started" in metrics["sidebarText"]
    assert "Concepts" not in metrics["sidebarText"]
    assert "Guides" not in metrics["sidebarText"]
    assert "Protocol" not in metrics["sidebarText"]
    assert "Runtime" not in metrics["sidebarText"]
    assert "Tutorials" not in metrics["sidebarText"]
    assert "Reference" not in metrics["sidebarText"]
    assert "Protocol Level" in tutorial_sidebar
    assert "Native Runtime" in tutorial_sidebar
    assert "Client Runtime" in tutorial_sidebar
    assert "Channels" not in tutorial_sidebar
    assert "HTTP API" not in tutorial_sidebar
    assert metrics["source"]["component"] == "source"
    assert metrics["sourceRepository"].startswith("Productive-Superintelligence/sssn")
    assert metrics["footer"]["height"] == pytest.approx(44, abs=1)
    assert metrics["footerMark"]["width"] == pytest.approx(100, abs=2)
    assert metrics["footerMark"]["height"] == pytest.approx(27, abs=2)
    assert "Roboto" in metrics["bodyFont"]
    assert "Roboto Mono" in metrics["codeFont"]

    visible_brands = [
        image for image in metrics["brandImages"] if image["display"] == "block"
    ]
    hidden_brands = [
        image for image in metrics["brandImages"] if image["display"] == "none"
    ]
    assert len(visible_brands) == 1
    assert visible_brands[0]["src"] == "assets/sssn-logo-text-dark.png#only-light"
    assert visible_brands[0]["width"] == pytest.approx(274, abs=3)
    assert visible_brands[0]["height"] == pytest.approx(90, abs=2)
    assert any(
        image["src"] == "assets/sssn-logo-text-white.png#only-dark"
        for image in hidden_brands
    )


def test_docs_mobile_chrome_keeps_visual_contract(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    chromium = chromium_executable()
    if not chromium:
        pytest.skip("Chromium executable is not available")

    site_dir = build_docs(tmp_path)

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=chromium,
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
        )
        page.goto(
            (site_dir / "index.html").as_uri(), wait_until="domcontentloaded"
        )
        page.wait_for_function(
            """
            () => {
              const diagrams = [...document.querySelectorAll('.md-typeset .mermaid')];
              return diagrams.length > 0 &&
                diagrams.every((diagram) =>
                  diagram.hasAttribute('data-mermaid-source') &&
                  diagram.querySelector('svg')
                );
            }
            """,
            timeout=5000,
        )
        metrics = page.evaluate(
            """
            () => {
              const inspect = (selector) => {
                const element = document.querySelector(selector);
                if (!element) {
                  return null;
                }
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return {
                  backgroundColor: style.backgroundColor,
                  color: style.color,
                  display: style.display,
                  height: rect.height,
                  src: element.getAttribute("src") || "",
                  width: rect.width,
                };
              };
              const images = (selector) =>
                [...document.querySelectorAll(selector)].map((element) => {
                  const style = getComputedStyle(element);
                  const rect = element.getBoundingClientRect();
                  return {
                    display: style.display,
                    height: rect.height,
                    src: element.getAttribute("src") || "",
                    width: rect.width,
                  };
                });
              return {
                bodyFont: getComputedStyle(document.body)
                  .getPropertyValue("--md-text-font-family")
                  .trim(),
                codeFont: getComputedStyle(document.body)
                  .getPropertyValue("--md-code-font-family")
                  .trim(),
                docWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
                footer: inspect(".md-footer-meta"),
                footerMark: inspect(".psi-footer-wordmark"),
                header: inspect(".md-header"),
                headerLogo: inspect(
                  ".md-header__button.md-logo img, .md-header__button.md-logo svg"
                ),
                headerNav: inspect(".psi-header-nav"),
                mermaid: inspect(".md-typeset .mermaid"),
                brandImages: images(".psi-brand img"),
                mermaidSvgs: images(".md-typeset .mermaid svg"),
              };
            }
            """
        )
        page.click('.md-header__button[for="__drawer"]')
        page.wait_for_timeout(350)
        drawer_metrics = page.evaluate(
            """
            () => {
              const inspect = (selector) => {
                const element = document.querySelector(selector);
                if (!element) {
                  return null;
                }
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                  return {
                    backgroundColor: style.backgroundColor,
                    color: style.color,
                    display: style.display,
                    height: rect.height,
                    src: element.getAttribute("src") || "",
                    width: rect.width,
                };
              };
              return {
                logo: inspect(
                  ".md-nav__button.md-logo img, .md-nav__button.md-logo svg"
                ),
                sections: inspect(".psi-drawer-sections"),
                sectionsText: document
                  .querySelector(".psi-drawer-sections")
                  ?.innerText.trim().replace(/\\s+/g, " ") || "",
                title: inspect('.md-nav--primary .md-nav__title[for="__drawer"]'),
              };
            }
            """
        )
        page.close()
        browser.close()

    assert metrics["docWidth"] <= metrics["viewportWidth"] + 1
    assert metrics["header"]["backgroundColor"] == "rgb(255, 255, 255)"
    assert metrics["footer"]["backgroundColor"] == "rgb(255, 255, 255)"
    assert metrics["header"]["color"] == "rgb(5, 5, 5)"
    assert metrics["footer"]["color"] == "rgb(5, 5, 5)"
    assert metrics["header"]["height"] == pytest.approx(49, abs=1)
    assert metrics["headerLogo"]["src"] == "assets/logo.svg"
    assert metrics["headerLogo"]["width"] == pytest.approx(24, abs=1)
    assert metrics["headerLogo"]["height"] == pytest.approx(24, abs=1)
    assert metrics["headerNav"]["display"] == "none"
    assert metrics["footer"]["height"] <= 72
    assert metrics["footerMark"]["width"] == pytest.approx(100, abs=2)
    assert metrics["footerMark"]["height"] == pytest.approx(27, abs=2)
    assert "Roboto" in metrics["bodyFont"]
    assert "Roboto Mono" in metrics["codeFont"]
    assert metrics["mermaid"]["width"] <= metrics["viewportWidth"]
    assert metrics["mermaidSvgs"][0]["width"] > metrics["viewportWidth"]
    assert drawer_metrics["title"]["backgroundColor"] == "rgb(255, 255, 255)"
    assert drawer_metrics["title"]["color"] == "rgb(5, 5, 5)"
    assert drawer_metrics["logo"]["src"] == "assets/logo.svg"
    assert drawer_metrics["logo"]["width"] == pytest.approx(48, abs=1)
    assert drawer_metrics["logo"]["height"] == pytest.approx(48, abs=1)
    assert drawer_metrics["sections"]["display"] == "grid"
    assert "Overview" in drawer_metrics["sectionsText"]
    assert "Tutorials" in drawer_metrics["sectionsText"]
    assert "Reference" in drawer_metrics["sectionsText"]
    assert "Getting Started" not in drawer_metrics["sectionsText"]

    visible_brands = [
        image for image in metrics["brandImages"] if image["display"] == "block"
    ]
    hidden_brands = [
        image for image in metrics["brandImages"] if image["display"] == "none"
    ]
    assert len(visible_brands) == 1
    assert visible_brands[0]["src"] == "assets/sssn-logo-text-dark.png#only-light"
    assert visible_brands[0]["width"] < metrics["viewportWidth"]
    assert 63 <= visible_brands[0]["height"] <= 67
    assert any(
        image["src"] == "assets/sssn-logo-text-white.png#only-dark"
        for image in hidden_brands
    )


def test_docs_keep_light_brand_styles(tmp_path):
    site_dir = build_docs(tmp_path)
    custom_css = (site_dir / "stylesheets" / "custom.20260629.css").read_text(
        encoding="utf-8"
    )
    mermaid_js = (site_dir / "javascripts" / "mermaid-init.20260629.js").read_text(
        encoding="utf-8"
    )
    index_html = (site_dir / "index.html").read_text(encoding="utf-8")
    mermaid_svg_css = css_block(custom_css, ".md-typeset .mermaid svg")

    assert ".md-header," in custom_css
    assert ".md-tabs {" in custom_css
    assert ".md-header--shadow" in custom_css
    assert "background-color: #ffffff;" in custom_css
    assert "--md-footer-fg-color--light: var(--psi-ink);" in custom_css
    assert ".md-footer-meta__inner" in custom_css
    assert "display: flex;" in custom_css
    assert "justify-content: space-between;" in custom_css
    assert '--md-text-font: "Roboto";' in custom_css
    assert '--md-code-font: "Roboto Mono";' in custom_css
    assert "--md-text-font-family" in custom_css
    assert '"Roboto Mono", SFMono-Regular' in custom_css
    assert "-apple-system" in custom_css
    assert "--psi-brand-width: 20rem;" in custom_css
    assert "--psi-brand-height: 4.5rem;" in custom_css
    assert "--psi-brand-height: 3.25rem;" in custom_css
    assert "--psi-diagram-bg: #ffffff;" in custom_css
    assert "--psi-diagram-ink: #050505;" in custom_css
    assert ".md-header__button.md-logo" in custom_css
    assert "width: 1.2rem;" in custom_css
    assert ".md-nav--primary .md-nav__title .md-nav__button.md-logo" in custom_css
    assert "width: 2.4rem;" in custom_css
    assert ".md-search__form .md-icon svg" in custom_css
    assert "fill: currentcolor;" in custom_css
    assert ".psi-header-nav" in custom_css
    assert ".psi-header-nav__link" in custom_css
    assert ".psi-drawer-sections" in custom_css
    assert ".psi-drawer-sections__link" in custom_css
    assert "overflow-x: auto;" in custom_css
    assert ".md-nav__button.md-logo" in custom_css
    assert ".psi-footer-wordmark" in custom_css
    assert 'background-image: url("../assets/sssn-logo-text-dark.png");' in custom_css
    assert ".psi-footer-text" in custom_css
    assert "clip-path: inset(50%);" in custom_css
    assert "white-space: nowrap;" in custom_css
    assert ".md-social__link" in custom_css
    assert "height: 2rem;" in custom_css
    assert ".psi-brand img" in custom_css
    assert "max-height: var(--psi-brand-height);" in custom_css
    assert "max-width: min(var(--psi-brand-width), 100%);" in custom_css
    assert 'img[src$="#only-dark"]' in custom_css
    assert ".md-typeset .mermaid svg" in custom_css
    assert "max-width: 100%;" in mermaid_svg_css
    assert "min-width: 0;" in mermaid_svg_css
    assert "width: 100%;" in mermaid_svg_css
    assert "--mermaid-font-family" in custom_css
    assert ".md-typeset .mermaid foreignObject" in custom_css
    assert "line-height: 1.2;" in custom_css
    assert ".md-typeset .mermaid text" in custom_css
    assert ".md-typeset .mermaid .node rect" in custom_css
    assert ".md-typeset .mermaid .edgePath path" in custom_css
    assert ".md-typeset .mermaid marker path" in custom_css
    assert "var(--psi-diagram-ink)" in custom_css
    assert "var fontFamily" in mermaid_js
    assert "Roboto, -apple-system, BlinkMacSystemFont" in mermaid_js
    assert "window.mermaid.startOnLoad = false" in mermaid_js
    assert 'securityLevel: "loose"' in mermaid_js
    assert "flowchart:" in mermaid_js
    assert "htmlLabels: true" in mermaid_js
    assert "themeCSS:" in mermaid_js
    assert "nodeTextColor" in mermaid_js
    assert "useMaxWidth: true" in mermaid_js
    assert "data-mermaid-source" in mermaid_js
    assert "normalizeSource" in mermaid_js
    assert "sourceFor" in mermaid_js
    assert "diagramNodes" in mermaid_js
    assert "renderDiagrams" in mermaid_js
    assert "window.mermaid.run" not in mermaid_js
    assert "falling back to manual rendering" not in mermaid_js
    assert 'document.querySelectorAll(".md-typeset .mermaid, .mermaid")' in mermaid_js
    assert '!node.querySelector("svg")' in mermaid_js
    assert 'node.getAttribute("data-mermaid-rendering") !== "true"' in mermaid_js
    assert "Boolean(source && source.trim())" in mermaid_js
    assert 'node.setAttribute("data-mermaid-source", source)' in mermaid_js
    assert "data-mermaid-error" in mermaid_js
    assert "renderSequence" in mermaid_js
    assert "renderNodeSafely" in mermaid_js
    assert "Mermaid returned an empty SVG." in mermaid_js
    assert "renderAgain" in mermaid_js
    assert "rendering" in mermaid_js
    assert "scheduled" in mermaid_js
    assert "afterFontsReady" in mermaid_js
    assert "data-mermaid-rendering" in mermaid_js
    assert "window.mermaid.render" in mermaid_js
    assert "attempt < maxRetries" in mermaid_js
    assert "requestAnimationFrame" in mermaid_js
    assert "window.document$.subscribe(scheduleRender)" in mermaid_js
    assert 'window.addEventListener("load", scheduleRender)' in mermaid_js
    assert 'window.addEventListener("pageshow", scheduleRender)' in mermaid_js
    assert "renderRunning" not in mermaid_js
    assert "renderScheduled" not in mermaid_js
    assert 'container.getAttribute("data-mermaid-error") === "true"' not in mermaid_js
    assert "assets/logo.svg" in index_html
    assert "assets/sssn-logo-text-dark.png#only-light" in index_html
    assert "assets/sssn-logo-text-white.png#only-dark" in index_html
    assert "psi-header-nav" in index_html
    assert "psi-footer-wordmark" in index_html
    assert (
        "<div class=\"md-source__repository\">\n"
        "    Productive-Superintelligence/sssn\n"
        "  </div>"
        in index_html
    )
    assert 'data-md-component="source"' in index_html
    assert 'class="md-tabs"' not in index_html
    assert 'src="/assets/sssn-logo-text-dark.png"' not in index_html

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert '<p align="center">' in readme
    assert '<img src="assets/sssn-logo-text-dark.png" alt="SSSN" width="420">' in readme
    assert (site_dir / "CNAME").read_text(encoding="utf-8").strip() == "sssn.one"


def test_docs_nav_keeps_foldable_tutorial_groups():
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    assert "- navigation.sections" in config
    assert "- navigation.indexes" in config
    assert "- navigation.expand" not in config
    assert "- navigation.tabs" not in config
    assert "- navigation.tabs.sticky" not in config
    assert "scheme: slate" not in config
    assert "material/weather-night" not in config
    assert "  - Overview:\n      - Overview: index.md\n      - Getting Started:" in config
    assert "  - Protocol:\n      - Protocol: protocol/index.md" in config
    assert "      - Concepts:" in config
    assert "  - Runtime:\n      - Runtime: runtime/index.md" in config
    assert "      - Guides:" in config
    assert "  - Tutorials:\n      - Protocol Level:" in config
    assert "      - Native Runtime:" in config
    assert "      - Client Runtime:" in config
    assert "      - Composition:" in config
    assert "          - First Channel: tutorials/first-channel.md" in config
    assert "          - Local Store: tutorials/local-store.md" in config
    assert "          - HTTP Client: tutorials/http-client.md" in config
    assert "          - LLLM Tactic Processor: tutorials/lllm-tactic.md" in config


def test_http_api_reference_distinguishes_artifact_payload_and_metadata():
    reference = (ROOT / "docs" / "reference" / "http-api.md").read_text(
        encoding="utf-8"
    )

    assert "| `GET /artifacts/{id}` | Read artifact payload bytes. |" in reference
    assert (
        "| `GET /artifacts/{id}/metadata` | Read artifact metadata only. |"
        in reference
    )


def test_python_api_reference_documents_resource_name_segments():
    reference = (ROOT / "docs" / "reference" / "python-api.md").read_text(
        encoding="utf-8"
    )

    assert "Resource names:" in reference
    assert "must be non-empty path segments" in reference
    assert "avoid percent escapes, `.`, `..`, `/`" in reference
    assert "`\\`, and `:`" in reference
    assert "SSSNResolver.from_config(path)" in reference
    assert "local_store(ref)" in reference
    assert "client(ref)" in reference
    assert "resolver config paths must be" in reference
    assert "non-empty and unpadded" in reference


def test_http_api_reference_lists_portable_endpoints():
    reference = (ROOT / "docs" / "reference" / "http-api.md").read_text(
        encoding="utf-8"
    )
    expected = {
        "POST /channels",
        "GET /channels",
        "GET /channels/{name}",
        "POST /events",
        "GET /events?channel=...",
        "GET /events/{id}",
        "POST /subscriptions",
        "GET /subscriptions/{id}",
        "POST /subscriptions/{id}/pull",
        "POST /artifacts",
        "GET /artifacts/{id}",
        "GET /artifacts/{id}/metadata",
        "PUT /snapshots/{name}",
        "GET /snapshots/{name}",
    }

    for endpoint in expected:
        assert f"| `{endpoint}` |" in reference
    assert "unique method/path pairs" in reference
    assert "reserved SSSN service routes" in reference
    assert "Endpoint paths, names, and tags must avoid whitespace" in reference
    assert "percent escapes" in reference
    assert "network-path prefixes" in reference


def test_cli_reference_lists_portable_resource_commands():
    reference = (ROOT / "docs" / "reference" / "cli.md").read_text(
        encoding="utf-8"
    )
    expected = [
        "create-channel events --schema demo.Event --metadata",
        "append events",
        "--correlation-id corr-1 --parent-id <event-id>",
        "query-events events --limit 10",
        "get-event <event-id>",
        "create-subscription events --id worker --kind message",
        "pull-subscription worker --limit 10",
        "get-subscription worker",
        "write-artifact 'hello' --media-type text/plain --event-id <event-id>",
        "get-artifact <artifact-id>",
        "read-artifact <artifact-id>",
        "put-snapshot latest",
        "--source-event-id <event-id>",
        "get-snapshot latest",
    ]

    for command in expected:
        assert command in reference


def test_psihub_package_guide_documents_endpoint_metadata():
    guide = (ROOT / "docs" / "guides" / "psihub-packages.md").read_text(
        encoding="utf-8"
    )

    assert "custom_endpoints=[channel_tail]" in guide
    assert '"path": "/channels/{name}/tail"' in guide
    assert "create_app(..., custom_endpoints=...)" in guide
    assert (
        "python -m pytest tests/test_psihub_integration.py tests/test_examples.py -q"
        in guide
    )
    assert "SSSNResolver.from_config" in guide
    assert "psi://demo/events/channels/raw" in guide
    assert "loads only `/channels/` and `/snapshots/` refs" in guide
    assert "All binding keys must still be valid `psi://`" in guide
    assert "malformed SSSN and non-SSSN refs fail validation" in guide


def test_public_text_does_not_use_staging_name():
    text_paths = [ROOT / "README.md"]
    text_paths.extend((ROOT / "docs").rglob("*.md"))
    text_paths.extend(
        path
        for path in (ROOT / "examples").rglob("*")
        if path.suffix in {".md", ".py", ".toml", ".yaml", ".yml"}
    )

    for path in text_paths:
        text = path.read_text(encoding="utf-8")
        assert "LLLM v2" not in text, path
        assert "lllmv2" not in text, path
        assert "SSSN v2" not in text, path
        assert "sssnv2" not in text, path


def test_tutorials_keep_step_by_step_shape():
    required = [
        "Goal:",
        "## Prerequisites",
        "## Files Used",
        "## Verify",
        "Expected output:",
        "Next,",
    ]

    for path in sorted((ROOT / "docs" / "tutorials").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for marker in required:
            assert marker in text, f"{path.relative_to(ROOT)} missing {marker}"


def test_readme_and_docs_local_links_resolve():
    pattern = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
    text_paths = [ROOT / "README.md"]
    text_paths.extend((ROOT / "docs").rglob("*.md"))
    skip_prefixes = ("http://", "https://", "mailto:", "#")

    missing = []
    for path in sorted(text_paths):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1).strip()
            if not target or target.startswith(skip_prefixes) or "://" in target:
                continue
            target = target.split("#", 1)[0].split("?", 1)[0]
            if not target:
                continue
            if not (path.parent / unquote(target)).resolve().exists():
                missing.append(f"{path.relative_to(ROOT)} -> {match.group(1)}")

    assert missing == []


def test_docs_local_asset_references_resolve():
    patterns = [
        re.compile(r'\bsrc="([^"]+)"'),
        re.compile(r"url\([\"']?([^\"')]+)[\"']?\)"),
        re.compile(r"!\[[^\]]*\]\(([^)]+)\)"),
    ]
    text_paths = [ROOT / "README.md"]
    text_paths.extend((ROOT / "docs").rglob("*.md"))
    text_paths.extend((ROOT / "docs" / "stylesheets").glob("*.css"))
    skip_prefixes = ("http://", "https://", "mailto:", "data:", "#")

    missing = []
    for path in sorted(text_paths):
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            for match in pattern.finditer(text):
                target = match.group(1).strip()
                if (
                    not target
                    or target.startswith(skip_prefixes)
                    or "://" in target
                ):
                    continue
                target = target.split("#", 1)[0].split("?", 1)[0]
                if not target:
                    continue
                if not (path.parent / unquote(target)).resolve().exists():
                    missing.append(
                        f"{path.relative_to(ROOT)} -> {match.group(1)}"
                    )

    assert missing == []
