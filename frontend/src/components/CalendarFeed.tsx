import { useState } from "react";
import styled from "styled-components";
import { api, type Feed } from "../api";
import { Alert, Button, Input, Lead, Row, Small } from "../ui";

// The private calendar feed (/calendar.ics?token=…): study blocks, deadlines with alarms and
// your unavailabilities in one calendar. The token is a secret in the URL because calendar
// apps can't sign in; "New link" revokes the old one (backend: app/api/ics.py).

const FeedUrl = styled(Input)`
  font-size: ${({ theme }) => theme.fontSizes.sm};
  background: ${({ theme }) => theme.colors.surfaceSunken};
`;

export function CalendarFeed() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function show() {
    try {
      setFeed(await api.feed());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function rotate() {
    if (!window.confirm("Make a new link? Calendars subscribed with the old link stop updating.")) return;
    try {
      setFeed(await api.newFeed());
      setCopied(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function copy() {
    if (!feed) return;
    try {
      await navigator.clipboard.writeText(feed.url);
      setCopied(true);
    } catch {
      window.prompt("Copy this link", feed.url);
    }
  }

  return (
    <>
      <Lead $small>
        One calendar with your study blocks, deadlines (with alarms) and the times you can't study. Subscribe once:
        each time you save the schedule, your calendar app picks up the new plan at its next refresh (usually within
        a few hours). The link is private: anyone who has it can see your plan.
      </Lead>
      {!feed ? (
        <Row>
          <Button $variant="primary" onClick={show}>Show subscription link</Button>
        </Row>
      ) : (
        <>
          <FeedUrl readOnly value={feed.url} onFocus={(e) => e.currentTarget.select()} aria-label="Calendar link" />
          <Row>
            <Button as="a" $variant="primary" href={feed.webcal}>Subscribe on this device</Button>
            <Button $variant="outline" onClick={copy}>{copied ? "Copied ✓" : "Copy link"}</Button>
            <Button $variant="ghost" onClick={rotate}>New link</Button>
          </Row>
          <Small $muted>
            iPhone: tap Subscribe. Google Calendar: Settings → Add calendar → From URL, paste the
            link. Outlook: Add calendar → Subscribe from web.
          </Small>
        </>
      )}
      {error && <Alert>{error}</Alert>}
    </>
  );
}
