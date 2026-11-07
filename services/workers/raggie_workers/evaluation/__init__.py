# SPDX-License-Identifier: Apache-2.0

"""Auto-evaluator: faithfulness and citation scoring of completed chats on a separate
lane. Consumes raggie.chat.completed, scores answer-vs-context, flags low
scores — never blocking or starving the chat/retrieval hot path."""
