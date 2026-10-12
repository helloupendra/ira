# IRA

**Hey Ira.** A self-hosted voice assistant over your own data and tools.

IRA lets a developer give a small business a voice and text assistant that
knows the business's own data: appointments, orders, stock, bookings. You
register *read tools* (functions that look things up) and *action tools*
(functions that change something). Ira answers on the web, over an HTTP API
and on Telegram, by text or voice. It only **proposes** an action; your code
runs it after the owner confirms with a PIN.

- **Any model.** OpenAI-compatible endpoints, the Anthropic Messages API and
  Amazon Bedrock, with fallback chains, cool-downs and a cost log.
- **Voice both ways.** A mic in the browser and Telegram voice notes in;
  spoken replies out.
- **Safe by construction.** PIN-confirmed actions that run once, accounts with
  roles, scoped API tokens, and a PIN that never passes through a model.
- **Runs with no key.** A keyword-routing demo provider makes the example
  clinic work out of the box.

## Where to go next

| If you want to | Read |
| --- | --- |
| Run the demo in five minutes | [Getting started](getting-started.md) |
| Understand tools, actions, tiers and channels | [Concepts](concepts.md) |
| See how the pieces fit | [Architecture](architecture.md) |
| Run it for a business | [Admin guide](admin-guide.md), [Deployment](deployment.md) |
| Call it from your own app | [API](api.md) |
| Know what it protects and how | [Security](security.md) |
| Read a complete example | [Sunrise Dental Clinic](examples/clinic.md) |
