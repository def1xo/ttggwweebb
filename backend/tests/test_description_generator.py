from app.services.description_generator import (
    DescriptionPayload,
    TemplateDescriptionGenerator,
    should_regenerate_description,
    safe_generate_description,
)


def test_template_generator_produces_different_descriptions_for_different_titles():
    gen = TemplateDescriptionGenerator()
    out = []
    for i in range(10):
        txt = gen.generate(
            DescriptionPayload(
                title=f"Yeezy Model {i}",
                category="Кроссовки",
                colors=["green" if i % 2 else "black"],
                key_features=["амортизация", "легкий верх"],
            )
        )
        out.append(txt)

    assert len(set(out)) == 10


def test_do_not_regenerate_when_description_is_already_valid():
    existing = "Yeezy 350 с удобной посадкой и нейтральным дизайном для ежедневной носки."
    assert should_regenerate_description(existing, None, force_regen=False) is False



def test_safe_generate_description_fallback_when_generator_raises(monkeypatch):
    class Broken:
        source = "broken"
        def generate(self, payload):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.services.description_generator.get_description_generator", lambda: Broken())
    txt, src = safe_generate_description(DescriptionPayload(title="Yeezy 700", category="Кроссовки"))
    assert txt is not None and len(txt) > 10
    assert src == "template"
