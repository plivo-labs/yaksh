import Image from 'next/image';
import Link from 'next/link';
import { gitConfig } from '@/lib/shared';
import conversation from '../../images/conversation.png';

const repoUrl = `https://github.com/${gitConfig.user}/${gitConfig.repo}`;

const features = [
  {
    title: 'Real phone calls, not text',
    body: "Yaksh dials your agent's number through Plivo, so it tests what your customers hear: speech recognition, latency, interruptions and hang-ups.",
  },
  {
    title: 'Callers that act like people',
    body: 'Personas with their own voice, language and background noise: a cafe, a car, a TV, a second person in the room.',
  },
  {
    title: 'Verdicts you can trust',
    body: 'Judges check each call against your criteria and quote the transcript, and code checks every quote. When the simulated caller makes a mistake, the test is blocked, not failed.',
  },
  {
    title: 'Numbers that mean something',
    body: 'Pass rate, response time p50 and p90, talk-overs and dead air, each with a confidence interval, so a run of five calls does not look like proof.',
  },
  {
    title: 'Built for coding agents',
    body: 'The CLI lets Claude Code, Codex and other coding agents run your tests, read why calls failed, fix your agent and test again.',
  },
  {
    title: 'Your data stays yours',
    body: 'Run Yaksh on your own servers with your own provider accounts. Recordings, transcripts and results stay in your database and storage.',
  },
];

const steps = [
  { title: 'Add your agent', body: 'Import it from Plivo CX, Vapi, Retell or ElevenLabs, or give its number and what it does.' },
  { title: 'Write scenarios', body: "Write them yourself, or let Yaksh write them from your agent's brief and knowledge base." },
  { title: 'Run', body: 'Yaksh places the calls, records them and judges them.' },
  { title: 'Read the results', body: 'Each failed call shows the criterion it broke and the lines that prove it.' },
];

const quickStart = `git clone ${repoUrl} && cd ${gitConfig.repo}
cp docker/.env.example docker/.env
docker compose -f docker/compose.yaml up`;

export default function HomePage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 md:px-6">
      <section className="flex flex-col items-center pt-20 pb-12 text-center md:pt-28">
        <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-balance md:text-5xl">
          Find out how your voice agent behaves on real calls before your customers do.
        </h1>
        <p className="mt-6 max-w-2xl text-lg text-fd-muted-foreground text-balance">
          Yaksh calls your AI voice agent over a real phone line, plays a realistic caller, and tells you
          what went wrong, with the transcript line that proves it. Open source and self-hosted.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link
            href="/docs/quickstart"
            className="rounded-full bg-fd-primary px-5 py-2.5 text-sm font-medium text-fd-primary-foreground"
          >
            Get started
          </Link>
          <a
            href={repoUrl}
            className="rounded-full border border-fd-border px-5 py-2.5 text-sm font-medium hover:bg-fd-accent"
          >
            View on GitHub
          </a>
        </div>
      </section>

      <section className="pb-20">
        <Image
          src={conversation}
          alt="A failed test call in Yaksh: the caller gives all four booking details, the agent asks for the name again, and the judge fails the call and quotes the two lines that prove it."
          className="w-full rounded-xl border border-fd-border shadow-lg"
          sizes="(min-width: 1152px) 1104px, 100vw"
          priority
        />
      </section>

      <section className="pb-20">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">Why Yaksh</h2>
        <p className="mt-3 max-w-3xl text-fd-muted-foreground">
          A few test calls before each release catch the obvious bugs. They do not catch the agent that
          forgets to confirm a booking one call in five, or talks over a caller in a noisy street. Yaksh runs
          those calls for you, in volume, every time you change your agent.
        </p>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <div key={feature.title} className="rounded-xl border border-fd-border bg-fd-card p-5">
              <h3 className="font-medium">{feature.title}</h3>
              <p className="mt-2 text-sm text-fd-muted-foreground">{feature.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="pb-20">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">How it works</h2>
        <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((step, index) => (
            <li key={step.title} className="rounded-xl border border-fd-border p-5">
              <span className="text-sm text-fd-muted-foreground">{index + 1}</span>
              <h3 className="mt-1 font-medium">{step.title}</h3>
              <p className="mt-2 text-sm text-fd-muted-foreground">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="pb-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">Quick start</h2>
        <p className="mt-3 max-w-3xl text-fd-muted-foreground">
          You need Docker, a Plivo account with a phone number, and API keys for OpenAI or Azure OpenAI,
          Deepgram and ElevenLabs.
        </p>
        <pre className="mt-6 overflow-x-auto rounded-xl border border-fd-border bg-fd-card p-5 text-sm">
          <code>{quickStart}</code>
        </pre>
        <p className="mt-4 text-sm text-fd-muted-foreground">
          Then open http://localhost:8000 and follow the{' '}
          <Link href="/docs/quickstart" className="font-medium text-fd-foreground underline">
            quick start
          </Link>
          .
        </p>
      </section>

      <footer className="flex flex-wrap justify-between gap-4 border-t border-fd-border py-8 text-sm text-fd-muted-foreground">
        <span>
          BSD 2-Clause. By{' '}
          <a href="https://plivo.com" className="underline">
            Plivo
          </a>
          .
        </span>
        <span className="flex gap-4">
          <Link href="/docs">Docs</Link>
          <a href={repoUrl}>GitHub</a>
        </span>
      </footer>
    </main>
  );
}
