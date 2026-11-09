from app.pages import render_md, render_md_inline


def test_list_right_after_paragraph_is_rendered_as_list() -> None:
    html = str(render_md("**Что должно быть:**\n- статус `200`;\n- блок `args`."))
    assert "<ul>" in html and html.count("<li>") == 2


def test_lists_inside_code_blocks_are_untouched() -> None:
    html = str(render_md("```\nтекст\n- не список\n```"))
    assert "<ul>" not in html


def test_details_with_markdown_inside() -> None:
    html = str(
        render_md(
            '<details markdown="1">\n<summary>Проверь себя</summary>\n\n**ответ**\n\n</details>'
        )
    )
    assert "<details>" in html and "<strong>ответ</strong>" in html


def test_inline_has_no_paragraph() -> None:
    assert str(render_md_inline("`{}` и текст")) == "<code>{}</code> и текст"
