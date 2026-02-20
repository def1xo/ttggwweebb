from app.services.description_generator import (
    DescriptionPayload,
    TemplateDescriptionGenerator,
    should_regenerate_description,
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
