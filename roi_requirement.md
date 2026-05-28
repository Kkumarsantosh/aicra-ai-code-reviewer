Three items from my verification list remain unaddressed in this update. These aren't architectural problems — the tool works without them — but they determine whether the tool gets adopted long-term or abandoned after a month.

text

ITEM 1: UNLINKED WORK REPORT
═════════════════════════════
STATUS: NOT MENTIONED across two updates now

WHAT IT IS:
  A read-only weekly report showing commits not 
  linked to any Jira ticket, classified as either 
  "Routine" (merge commits, lint fixes, dependency 
  updates) or "Potential Feature Work" (actual 
  development that should probably have a ticket).

WHY IT MATTERS:
  You removed Ghost Ticket creation (correct).
  But the NEED that Ghost Tickets addressed still exists:
  
  "We want to know if developers are doing significant 
   work that isn't being tracked in Jira."
  
  Ghost Tickets solved this the WRONG way (auto-creating junk).
  The Unlinked Work Report solves it the RIGHT way 
  (informing, not automating).
  
  Without this report, you have a VISIBILITY GAP.
  Work happens. Nobody knows about it. 
  That's the exact problem the original tool tried to solve.

EFFORT TO BUILD:
  This is a SMALL feature. Maybe 2-3 days of work.
  
  Logic:
    1. Get all commits in date range
    2. For each commit, check if commit message or 
       branch name references a Jira ticket (regex match)
    3. Commits without Jira reference → "unlinked"
    4. Classify unlinked commits:
       - Author is bot → Routine
       - Message matches "merge|revert|lint|format|bump" → Routine
       - Files changed < 3 AND lines changed < 30 → Routine
       - Everything else → Potential Feature Work
    5. Display as a simple list grouped by classification

PRIORITY: HIGH for next sprint
  Without this, the tool is missing one of its 
  four core value propositions.


ITEM 2: RISK DISMISSAL WITH REASON
═══════════════════════════════════
STATUS: NOT MENTIONED across two updates

WHAT IT IS:
  When a risk alert fires (e.g., "Large change without tests"),
  a team lead can click [Dismiss] and provide a reason
  (e.g., "Covered by integration tests").
  
  The alert doesn't appear again for that specific case.

WHY IT MATTERS:
  Without dismissal, here's what happens:

  Week 1: 5 risk alerts. Team lead reviews all 5.
          3 are real. 2 are false positives.
          Team lead takes action on the 3 real ones.
          The 2 false positives just sit there.

  Week 2: 7 risk alerts. But 2 are the SAME false 
          positives from last week. Plus 5 new ones.
          Team lead reviews 7, but recognizes 2 are repeats.
          Slightly annoyed.

  Week 3: 9 risk alerts. 2 are the same old false positives.
          3 are new false positives. 4 are real.
          Team lead is now spending time re-evaluating 
          alerts they've already decided aren't real.
          Frustration growing.

  Week 6: 15 risk alerts. Team lead stops checking.
          "That thing always has alerts, most aren't real."
          The risk detection feature is now DEAD.
          
  This is called ALERT FATIGUE. It kills every 
  monitoring tool that doesn't handle it.

EFFORT TO BUILD:
  Small feature. 1-2 days.
  
  Logic:
    1. Add a "dismissed_risks" database table:
       id, risk_hash, dismissed_by, reason, dismissed_at
    2. Generate a unique hash for each risk alert 
       (based on file path + risk type + approximate content)
    3. Before displaying alerts, filter out dismissed ones
    4. UI: Add [Dismiss] button with required reason field
    5. UI: Add "Show dismissed" toggle to see past dismissals

PRIORITY: HIGH for next sprint
  Without this, risk detection becomes noise 
  within 4-6 weeks. Guaranteed.


ITEM 3: JIRA API TOKEN READ-ONLY VERIFICATION
══════════════════════════════════════════════
STATUS: NOT MENTIONED across two updates

WHAT IT IS:
  Verify that the Jira API token itself (at the Jira 
  admin level) has read-only permissions, not just 
  that the code doesn't call write endpoints.

WHY IT MATTERS:
  You confirmed: "Code doesn't write to Jira" ✅
  But that's Layer 1 defense only.
  
  Layer 2 defense: Token CAN'T write even if code tries.
  
  This is a 5-minute task for whoever manages Jira admin.
  Either create a new read-only token or verify the 
  existing token's permission scope.

EFFORT: 5-10 minutes for Jira admin

PRIORITY: Do this week. Takes almost no time.


What you should Should Do Next
text

THIS WEEK (2-3 days total):
═══════════════════════════

□ Verify Jira token is read-only at admin level
  (5 minutes, not a development task)

□ Build Unlinked Work Report
  (2 days — logic is straightforward, mostly 
   git log parsing and simple classification)

□ Build Risk Dismissal with reason
  (1 day — database table, filter logic, UI button)


NEXT SPRINT:
════════════

□ Historical Trend Charts (4-week rolling)
  This is the #1 feature request executives will have.
  "Show me if we're getting better or worse."

□ Weekly Summary Notification (Email or Slack)
  Executives won't visit the dashboard daily.
  Push key metrics to them weekly.

□ High Churn File Detection
  Files changed >10 times in 4 weeks = instability signal.


FUTURE SPRINT:
══════════════

□ Stale PR Detection (needs GitHub/GitLab API)
□ Context Notes on quality spikes
□ Export to PDF
□ Integration between Engineering Intelligence 
  and FDS Gap Analyzer dashboards
Final Assessment Across Both Tools
text

┌─────────────────────────────────────────────────────────┐
│  TOOL STATUS OVERVIEW                                   │
├──────────────────────┬────────┬──────────────────────────┤
│  Tool                │ Grade  │ Next Step                │
├──────────────────────┼────────┼──────────────────────────┤
│  FDS Gap Analyzer    │  B     │ Run 37-page validation   │
│                      │        │ test THIS WEEK           │
│                      │        │                          │
│  Engineering         │  A-    │ Build Unlinked Work      │
│  Intelligence        │        │ Report + Risk Dismissal  │
│                      │        │ THIS WEEK                │
└──────────────────────┴────────┴──────────────────────────┘

Both tools are architecturally sound.
Both tools follow the correct philosophy.
Both tools need validation/completion of small items 
before they're ready for team-wide rollout.

RECOMMENDED ROLLOUT PLAN:
═════════════════════════

Week 1: Complete remaining items listed above
Week 2: Run validation tests on both tools
Week 3: Pilot with ONE team (your own team ideally)
Week 4: Collect feedback, fix issues
Week 5: Roll out to second team
Week 6: Company-wide availability
