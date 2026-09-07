---
name: copy-to-slack
description: Copy a Slack-ready message to the macOS clipboard as rich HTML plus plain text. Use when the user asks to draft or paste formatted Slack content with lists, paragraphs, inline code, or rich formatting.
compatibility: Requires macOS and the osascript command with JavaScript for Automation support.
---

# Copy to Slack

Use the bundled script to put both representations on the clipboard:

- `public.html` for Slack and other rich-text applications
- `public.utf8-plain-text` as a fallback for plain-text applications

This lets structured content such as lists and paragraphs paste as rich content
where supported, while retaining a readable fallback.

## Prepare the message

Write the plain-text fallback to one UTF-8 file and the HTML representation to
another. Escape user text before inserting it into HTML (`&`, `<`, and `>` at a
minimum). Normal `http`, `https`, and `mailto` links are allowed. The bundled
script strips active elements such as `<script>`, `<style>`, `<iframe>`,
`<object>`, and `<embed>`, removes event-handler attributes such as `onclick`,
and rejects unsafe URL schemes such as `javascript:` and `data:`. Use `<p>`,
`<ul>`, `<ol>`, `<li>`, `<br>`, and `<code>` for normal
content. Use `<strong>...</strong>` for bold and `<em>...</em>` for italics.
For section labels, use `<p><strong>Section name</strong></p>`: Slack may
flatten `<h1>`–`<h6>` into ordinary text. For code blocks, use
`<pre><code>...</code></pre>` and preserve newlines inside the element.

For example, `message.txt` might contain:

```text
Project update

- First item
- Second item
```

and `message.html` might contain:

```html
<p><strong>Project update</strong></p>
<ul>
  <li>First item</li>
  <li>Second item</li>
</ul>
<p>Run <code>make test</code> to validate changes.</p>
<pre><code>python -m unittest discover -s tests -v
</code></pre>
```

## Copy both representations

Run:

```bash
python .harness/skills/copy-to-slack/scripts/copy_to_slack.py \
  --html-file message.html < message.txt
```

The script does not print either representation or clipboard contents. Report
only whether the operation succeeded or why it failed.

## Slack notes

- Use semantic HTML for structure instead of relying on Markdown markers.
- Keep the plain-text version readable because not every application consumes
  HTML clipboard data.
- A literal `@name` is not guaranteed to notify a person; select the user in
  Slack or use Slack's user ID form, such as `<@U01234567>`.
- Do not add bold, italics, links, emojis, or code blocks unless requested.
