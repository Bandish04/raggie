## Summary

<!-- What does this change do, in 2–5 lines? -->

## Linked issue

<!-- e.g. Fixes #123 -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change (behaviour, API, configuration or data model)
- [ ] Documentation
- [ ] Refactor / tests / build

## Checklist

- [ ] All commits are signed off (`git commit -s`, see [CONTRIBUTING.md](../CONTRIBUTING.md#developer-certificate-of-origin-dco))
- [ ] Tests added or updated (a bug fix starts with a failing test)
- [ ] `make lint` and `make test` pass for the parts I changed
- [ ] Web changes: `pnpm lint`, `pnpm exec tsc --noEmit`, `pnpm test:unit`, `pnpm i18n:check` and `pnpm build` pass
- [ ] New HTTP routes have an authorization matrix entry (edge `authz_matrix_test.go` / control plane `authz_policy.yaml`)
- [ ] New environment variables are in `.env.example` with a comment and a safe default, and `docs/configuration.md` was regenerated (`make config-docs`)
- [ ] Docs updated for user- or operator-visible changes
- [ ] No secrets, real customer data or `.env` files included
- [ ] UI changes include screenshots (TR and EN if text changed)

## Commands run

```text
# paste the commands you ran and their result
```

## Risks and follow-ups

<!-- Anything reviewers should watch, rollout notes, known gaps. -->
