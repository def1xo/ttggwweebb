from app.services.description_generator import DescriptionPayload, TemplateDescriptionGenerator, should_regenerate_description


def test_template_generator_varies_by_title():
    gen = TemplateDescriptionGenerator()
    out = {
        gen.generate(DescriptionPayload(title=f"Yeezy {i}", category="Кроссовки", colors=["green"]))
        for i in range(10)
    }
    assert len(out) == 10


def test_should_not_regenerate_normal_description():
    txt = "Nike Vomero 5 — лаконичные кроссовки с дышащим верхом и мягкой амортизацией на каждый день."
    assert should_regenerate_description(txt, force_regen=False) is False
