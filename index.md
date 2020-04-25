---

layout: col-sidebar
title: OWASP Toronto
tags: canada
level: 4
region: North America
---

![Toronto Chapter Logo](assets/images/OWASPTorontoChapterLogo.jpg)

Welcome to the Toronto chapter homepage.


Upcoming Sessions
-----------------

**Date/Time**: May 6, 2020, 6:30 PM to 8:30 PM EDT

**Location**: Virtually on YouTube: https://www.youtube.com/watch?v=AJhn2aryehY

**Presentation summary:**

**Detect complex code patterns using semantic grep**

In this talk we’ll discuss a program analysis tool we’re developing called sgrep. It's a multilingual semantic tool for writing security and correctness queries on source code (for Python, Java, Go, C, and JS) with a simple “grep-like” interface. The original author, Yoann Padioleau, worked on sgrep’s predecessor, Coccinelle, for Linux kernel refactoring, and later developed sgrep while at Facebook. He’s now full time with us at r2c.

sgrep is the query system underpinning Bento, a free open-source program analysis toolkit that finds bugs using custom analysis we’ve written and OSS code checks. Bento is ideal for security researchers, product security engineers, and developers who want to find complex code patterns without extensive knowledge of ASTs or advanced program analysis concepts.

For example, find subprocess calls with shell=True in Python using the query:
subprocess.open(..., shell=True)
This will even find snippets like:
import subprocess as s
s.open(f'rm {args}', shell=True)

Or find hardcoded credentials using the query:
boto3.client(..., aws_secret_access_key=”...”, aws_access_key_id=”...” )

**Presenter bio:**

**Drew Dennison**

Drew Dennison is the CTO & co-founder of r2c, a startup working to profoundly improve software security and reliability to safeguard human progress. Previously at Palantir, he led data-driven cyber insurance platform development and technical incident response on major data leaks for Fortune 100 companies. Drew received his degree in Computer Science from MIT. He lives in SF and spends his free time racing sailboats, camping, and trying to outsmart his two cats.
