# Governance

Raggie is a young project. This document describes how decisions are made
today and how that will change as the community grows.

## Current model: project lead (BDFL)

Raggie is led by **Ali Can Gündüz** ([@alicangunduz](https://github.com/alicangunduz)),
the project lead. The project lead:

- sets the direction and roadmap of the project;
- has the final say on technical and community decisions;
- manages releases, security advisories and repository settings;
- appoints and removes maintainers.

## How decisions are made

Most decisions happen in the open, on issues, discussions and pull requests,
through **lazy consensus**:

1. Someone proposes a change (an issue, a discussion or a pull request).
2. Anyone may comment, raise concerns or suggest alternatives.
3. If there are no unresolved objections after a reasonable time (usually a few
   days for small changes, longer for large ones), a maintainer may merge or
   accept it.
4. If people disagree and cannot reach agreement, the project lead decides and
   explains why.

Large or hard-to-reverse changes (new services, data model changes, breaking
API or configuration changes, license-relevant dependencies) should start as an
issue or discussion before any code is written.

Security fixes may be developed privately and merged without the usual public
discussion; see [SECURITY.md](SECURITY.md).

## Roles

- **Contributors** — anyone who opens an issue, reviews, writes docs or code.
  All contributions are welcome and follow [CONTRIBUTING.md](CONTRIBUTING.md).
- **Maintainers** — trusted contributors with merge rights, listed in
  [MAINTAINERS.md](MAINTAINERS.md).
- **Project lead** — see above.

### Maintainer responsibilities

- Review pull requests promptly and respectfully.
- Keep `main` releasable: tests, security checks and the project rules in
  CONTRIBUTING.md must stay green.
- Triage issues in their areas and help new contributors.
- Follow and uphold the [Code of Conduct](CODE_OF_CONDUCT.md).
- Handle security reports confidentially.

### Becoming a maintainer

1. Make sustained, high-quality contributions over a period of time (code,
   reviews, docs, triage or community support).
2. An existing maintainer nominates you, in public or to the project lead.
3. The project lead approves the nomination and grants access.

Maintainers who are inactive for six months, or who ask to step down, move to
the emeritus list in MAINTAINERS.md. They can return by asking.

## Evolving this model

Once the project has **at least three active maintainers**, governance moves to
a **maintainer council**: decisions that today rest with the project lead are
taken by majority vote of active maintainers, and this document is updated
accordingly. Changes to this document are proposed by pull request and need
the project lead's approval (later: a council vote).

## Code of Conduct

Everyone in the project's spaces follows the
[Code of Conduct](CODE_OF_CONDUCT.md). Reports go to the contact listed there
and are handled by the project lead (later: the maintainer council), who may
take any action described in its enforcement guidelines.

## Name and logo

The Raggie code is licensed under Apache-2.0, which does not grant rights to
the project name or logo. How you may use them is described in
[TRADEMARKS.md](TRADEMARKS.md).
