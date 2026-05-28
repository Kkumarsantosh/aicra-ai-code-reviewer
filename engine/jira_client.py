"""
Jira Bridge — Pulls active ticket context and epic descriptions for AICRA.
"""

import requests
from requests.auth import HTTPBasicAuth
from config import Config
from datetime import datetime, timedelta

class JiraClient:
    def __init__(self):
        self.url = Config.JIRA_URL
        self.email = Config.JIRA_EMAIL
        self.token = Config.JIRA_API_TOKEN
        self.auth = HTTPBasicAuth(self.email, self.token) if self.email and self.token else None

    def get_delivery_metrics(self, project_key, days=14):
        """Fetches delivery metrics for the last N days."""
        if not self.auth or not self.url or not project_key:
            return None

        completed_statuses = Config.JIRA_COMPLETED_STATUSES
        in_progress_statuses = Config.JIRA_IN_PROGRESS_STATUSES
        
        feature_types = Config.JIRA_FEATURE_TYPES
        bug_types = Config.JIRA_BUG_TYPES
        tech_debt_types = Config.JIRA_TECH_DEBT_TYPES
        research_types = Config.JIRA_RESEARCH_TYPES
        
        # New categories from manager feedback
        ops_types = ["Operations", "DevOps", "Infrastructure", "Deployment"]
        support_types = ["Support", "Customer Issue", "Incident"]

        # JQL to find issues completed in the last N days
        status_list = ",".join([f'"{s}"' for s in completed_statuses])
        jql = f'project = "{project_key}" AND status IN ({status_list}) AND resolved >= "-{days}d"'
        api_url = f"{self.url.rstrip('/')}/rest/api/3/search"
        
        try:
            params = {
                "jql": jql,
                "fields": "summary,issuetype,status,created,resolutiondate",
                "expand": "changelog",
                "maxResults": 100
            }
            resp = requests.get(api_url, auth=self.auth, params=params, timeout=15)
            if resp.status_code != 200:
                return None
                
            issues = resp.json().get('issues', [])
            
            metrics = {
                "features": 0,
                "bugs": 0,
                "tech_debt": 0,
                "research": 0,
                "ops": 0,
                "support": 0,
                "other": 0,
                "total": len(issues),
                "avg_cycle_time_days": 0,
                "composition": {
                    "Feature": 0, "Bug": 0, "Debt": 0, "Research": 0, 
                    "Operations": 0, "Support": 0, "Other": 0
                },
                "last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            total_active_seconds = 0
            count_with_cycle_time = 0
            
            for issue in issues:
                itype = issue['fields'].get('issuetype', {}).get('name', 'Other')
                
                cat = "Other"
                if itype in feature_types: cat = "Feature"
                elif itype in bug_types: cat = "Bug"
                elif itype in tech_debt_types: cat = "Debt"
                elif itype in research_types: cat = "Research"
                elif itype in ops_types: cat = "Operations"
                elif itype in support_types: cat = "Support"
                
                metrics['composition'][cat] += 1
                if cat == "Feature": metrics['features'] += 1
                elif cat == "Bug": metrics['bugs'] += 1
                elif cat == "Debt": metrics['tech_debt'] += 1
                elif cat == "Research": metrics['research'] += 1
                elif cat == "Operations": metrics['ops'] += 1
                elif cat == "Support": metrics['support'] += 1
                else: metrics['other'] += 1
                
                # ── Advanced Cycle Time Calculation (Active Work Time) ──
                changelog = issue.get('changelog', {}).get('histories', [])
                active_intervals = []
                current_start = None
                
                # Sort histories by created date
                sorted_histories = sorted(changelog, key=lambda x: x.get('created'))
                
                for history in sorted_histories:
                    timestamp_str = history.get('created')
                    ts = datetime.strptime(timestamp_str.split('.')[0] + timestamp_str[-5:], "%Y-%m-%dT%H:%M:%S%z")
                    
                    for item in history.get('items', []):
                        if item.get('field') == 'status':
                            to_status = item.get('toString')
                            
                            if to_status in in_progress_statuses and current_start is None:
                                current_start = ts
                            elif to_status in completed_statuses and current_start is not None:
                                active_intervals.append((ts - current_start).total_seconds())
                                current_start = None
                            elif to_status not in in_progress_statuses and to_status not in completed_statuses and current_start is not None:
                                active_intervals.append((ts - current_start).total_seconds())
                                current_start = None
                
                if current_start and issue['fields'].get('resolutiondate'):
                    res_str = issue['fields']['resolutiondate']
                    res_ts = datetime.strptime(res_str.split('.')[0] + res_str[-5:], "%Y-%m-%dT%H:%M:%S%z")
                    active_intervals.append((res_ts - current_start).total_seconds())

                issue_active_seconds = sum(active_intervals)
                if issue_active_seconds > 0:
                    total_active_seconds += issue_active_seconds
                    count_with_cycle_time += 1
            
            if count_with_cycle_time > 0:
                metrics['avg_cycle_time_days'] = round(total_active_seconds / count_with_cycle_time / 86400.0, 1)
            
            return metrics
        except Exception as e:
            print(f"      [Jira Metrics Error] {e}")
            return None

    def get_quality_trends(self, project_key):
        """Fetches quality trends (bugs vs features) for the last 4 weeks."""
        if not self.auth or not self.url or not project_key:
            return None

        now = datetime.now()
        weeks = []
        for i in range(4):
            end_date = now - timedelta(days=7*i)
            start_date = now - timedelta(days=7*(i+1))
            
            end_str = end_date.strftime('%Y-%m-%d')
            start_str = start_date.strftime('%Y-%m-%d')
            
            jql = f'project = "{project_key}" AND resolved >= "{start_str}" AND resolved < "{end_str}"'
            api_url = f"{self.url.rstrip('/')}/rest/api/3/search"
            
            try:
                params = {"jql": jql, "fields": "issuetype", "maxResults": 100}
                resp = requests.get(api_url, auth=self.auth, params=params, timeout=10)
                if resp.status_code == 200:
                    issues = resp.json().get('issues', [])
                    features = len([i for i in issues if i['fields'].get('issuetype', {}).get('name') in Config.JIRA_FEATURE_TYPES])
                    bugs = len([i for i in issues if i['fields'].get('issuetype', {}).get('name') in Config.JIRA_BUG_TYPES])
                    
                    weeks.append({
                        "label": f"Week {4-i}",
                        "period": f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d')}",
                        "features": features,
                        "bugs": bugs,
                        "ratio": round(bugs / features, 2) if features > 0 else 0
                    })
            except:
                weeks.append({"label": f"Week {4-i}", "features": 0, "bugs": 0, "ratio": 0})
        
        weeks = weeks[::-1]
        for i in range(1, len(weeks)):
            prev_ratio = weeks[i-1]['ratio']
            curr_ratio = weeks[i]['ratio']
            if prev_ratio > 0 and (curr_ratio / prev_ratio) > 1.5:
                weeks[i]['spike_detected'] = True
                weeks[i]['spike_message'] = f"⚠️ Quality spike detected (+{round((curr_ratio/prev_ratio - 1) * 100)}%)"
            else:
                weeks[i]['spike_detected'] = False
        return weeks

    def get_business_alignment(self, project_key):
        """Fetches business alignment data (Epic progress and unaligned work)."""
        if not self.auth or not self.url or not project_key:
            return None

        api_url = f"{self.url.rstrip('/')}/rest/api/3/search"
        status_list = ",".join([f'"{s}"' for s in Config.JIRA_COMPLETED_STATUSES])
        total_jql = f'project = "{project_key}" AND status IN ({status_list}) AND resolved >= "-30d"'
        
        total_resolved = 0
        try:
            res = requests.get(api_url, auth=self.auth, params={"jql": total_jql, "maxResults": 0}, timeout=10)
            if res.status_code == 200:
                total_resolved = res.json().get('total', 0)
        except: pass

        jql = f'project = "{project_key}" AND issuetype = Epic AND status != "Done"'
        alignment_data = {
            "objectives": [],
            "total_resolved_30d": total_resolved,
            "aligned_resolved_30d": 0,
            "unaligned_pct": 0,
            "last_mapped": datetime.now().strftime("%Y-%m-%d"),
            "top_unaligned_epics": []
        }
        
        try:
            params = {"jql": jql, "fields": "summary,status", "maxResults": 20}
            resp = requests.get(api_url, auth=self.auth, params=params, timeout=10)
            if resp.status_code != 200:
                return alignment_data
                
            epics = resp.json().get('issues', [])
            for epic in epics:
                epic_key = epic['key']
                epic_name = epic['fields'].get('summary', 'Unnamed Epic')
                child_jql = f'parent = "{epic_key}"'
                child_resp = requests.get(api_url, auth=self.auth, params={"jql": child_jql, "fields": "status,resolved", "maxResults": 100}, timeout=10)
                
                if child_resp.status_code == 200:
                    children = child_resp.json().get('issues', [])
                    total = len(children)
                    done = len([c for c in children if c['fields'].get('status', {}).get('name') in Config.JIRA_COMPLETED_STATUSES])
                    alignment_data['aligned_resolved_30d'] += done
                    alignment_data['objectives'].append({
                        "objective": epic_name,
                        "key": epic_key,
                        "total_tickets": total,
                        "completed_tickets": done,
                        "progress_pct": round(done / total * 100) if total > 0 else 0,
                        "status": "On Track" if (done/total if total > 0 else 1) > 0.5 else "At Risk"
                    })
            
            if total_resolved > 0:
                unaligned_count = max(0, total_resolved - alignment_data['aligned_resolved_30d'])
                alignment_data['unaligned_pct'] = round(unaligned_count / total_resolved * 100)
            return alignment_data
        except Exception as e:
            print(f"      [Jira Alignment Error] {e}")
            return alignment_data

    def get_issue_context(self, ticket_id):
        """Fetches summary, description and epic info for a given ticket."""
        if not self.auth or not self.url or ticket_id == "N/A":
            return None

        api_url = f"{self.url.rstrip('/')}/rest/api/3/issue/{ticket_id}"
        try:
            resp = requests.get(api_url, auth=self.auth, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                fields = data.get('fields', {})
                context = {
                    "key": ticket_id,
                    "summary": fields.get('summary', ''),
                    "description": fields.get('description', ''),
                    "status": fields.get('status', {}).get('name', ''),
                    "priority": fields.get('priority', {}).get('name', ''),
                    "project": fields.get('project', {}).get('name', '')
                }
                epic_field = fields.get('parent') or fields.get('customfield_10008')
                if epic_field:
                    context['epic'] = epic_field.get('fields', {}).get('summary', 'General Epic')
                return context
            return None
        except Exception as e:
            print(f"      [Jira Bridge Error] {e}")
            return None

    def get_issue_basic(self, ticket_id):
        """Fetches basic info (summary, status) for a ticket."""
        if not self.auth or not self.url or not ticket_id:
            return None
        api_url = f"{self.url.rstrip('/')}/rest/api/3/issue/{ticket_id}"
        try:
            resp = requests.get(api_url, auth=self.auth, params={"fields": "summary,status"}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "key": ticket_id,
                    "summary": data['fields'].get('summary', ''),
                    "status": data['fields'].get('status', {}).get('name', ''),
                    "url": f"{self.url.rstrip('/')}/browse/{ticket_id}"
                }
            return None
        except: return None
