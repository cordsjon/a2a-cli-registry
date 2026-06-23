from jinja2 import Environment, PackageLoader


_ENV = Environment(
    loader=PackageLoader("core.web", "templates"),
    autoescape=True,
)


def render_overview_html(model) -> str:
    template = _ENV.get_template("overview.html")
    return template.render(model=model)
