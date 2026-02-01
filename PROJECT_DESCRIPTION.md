Darwin is an autonomous feedback-to-fix pipeline that gets better at writing code the more humans review it.

It scrapes user feedback from Reddit, forums, and any website using Browserbase + Stagehand for AI-powered extraction. Signals are clustered via semantic embeddings, classified as bugs/features/UX issues, then an AI agent writes fixes and opens PRs.

The key: Darwin learns from every code review. When reviewers comment "use early returns" or "prefer composition," Darwin extracts these as style rules ranked by usage. Merged PRs are stored with embeddings so similar bugs get few-shot examples from past fixes. Review feedback triggers automatic retries. Darwin's fixes require fewer review cycles as it internalizes team patterns.

Redis Stack powers the learning loop—vector search for clustering and fix retrieval, queues for async processing, and storage for style rules and fix memory.

Frontend built with v0 by Vercel.