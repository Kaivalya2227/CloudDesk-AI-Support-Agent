"""
load_kb_articles.py

Loads a fixed set of hand-written knowledge base articles into the database.
Unlike the other generators, this data is NOT randomly generated -- KB articles
need to read like genuine help-center content, so they're written out directly
below and just inserted as-is.

Run this AFTER create_database.py:
    python load_kb_articles.py

Re-running this script wipes and reloads the knowledge_base_articles table only.
"""

import sqlite3

DB_NAME = "clouddesk.db"

KB_ARTICLES = [
    # --- billing ---
    ("What's included in each CloudDesk plan tier?",
     "CloudDesk offers three plan tiers. Starter ($29/month base, plus $5 per additional "
     "seat) includes core call routing, a single-level IVR menu, and standard reporting -- "
     "best for small teams up to 10 seats. Growth ($99/month base, plus $12 per additional "
     "seat) adds skill-based routing, multi-level IVR menus (up to 5 levels), CRM "
     "integrations, and advanced analytics -- suited to growing teams up to 50 seats. "
     "Enterprise ($249/month base, plus $25 per additional seat) adds priority queueing for "
     "VIP customers, custom webhook integrations, dedicated onboarding support, and SLA-backed "
     "uptime guarantees -- designed for larger teams with complex routing needs. Any plan can "
     "be upgraded at any time; downgrades take effect at the next renewal date.",
     "billing"),

    ("How is my monthly invoice calculated?",
     "Your invoice is calculated based on your plan tier (Starter, Growth, or Enterprise) "
     "plus a per-seat charge for every active user on your account beyond the first seat. "
     "Invoices are generated automatically on your billing date each cycle and sent to the "
     "billing contact on file. You can view your full invoice history under Account > Billing.",
     "billing"),

    ("Why did my payment fail?",
     "Payments most commonly fail due to an expired card, insufficient funds, or your bank "
     "flagging the charge for verification. When a payment fails, we automatically retry "
     "after 3 days. If it fails a second time, your account status changes to 'locked' until "
     "payment is resolved. Update your card under Account > Billing > Payment Methods.",
     "billing"),

    ("How do I switch from monthly to annual billing?",
     "Account owners and admins can switch billing cycles from Account > Billing > Plan "
     "Settings. Switching to annual billing applies a discount and takes effect at your next "
     "renewal date; switching from annual to monthly mid-cycle is not supported and will take "
     "effect at the end of your current annual term.",
     "billing"),

    ("How do I add or remove seats from my subscription?",
     "Account owners and admins can adjust seat count under Account > Billing > Seats. Adding "
     "seats takes effect immediately and is prorated on your next invoice. Removing seats "
     "takes effect at your next renewal date, not immediately.",
     "billing"),

    ("Can I get a copy of a past invoice?",
     "Yes. All invoices are available under Account > Billing > Invoice History as downloadable "
     "PDFs. If you need an invoice reissued with different billing details, contact support "
     "with the invoice number and the correction needed.",
     "billing"),

    # --- ivr ---
    ("How do I change my IVR greeting?",
     "Go to Admin Console > IVR Builder > select your IVR flow > Greeting. You can upload a "
     "new audio file or use text-to-speech to generate one. Changes take effect immediately "
     "for new calls; calls already in the IVR menu will finish with the previous greeting.",
     "ivr"),

    ("Why is my IVR menu routing calls to the wrong queue?",
     "This is usually caused by a misconfigured menu option in the IVR Builder. Check that "
     "each keypress option is mapped to the intended queue under IVR Builder > Routing Rules. "
     "If options look correct but routing is still wrong, the issue may be a caching delay; "
     "allow up to 10 minutes after saving changes before testing again.",
     "ivr"),

    ("Why does my IVR menu loop back to the main menu instead of connecting to an agent?",
     "This typically happens when the selected queue has no available agents and no overflow "
     "destination configured. Set a fallback destination (voicemail, callback, or overflow "
     "queue) under IVR Builder > Routing Rules > Fallback Behavior.",
     "ivr"),

    ("How many IVR menu levels can I create?",
     "CloudDesk supports up to 5 nested menu levels per IVR flow on Growth and Enterprise "
     "plans, and up to 2 levels on Starter. If you need deeper menu structures, consider "
     "upgrading your plan or simplifying the flow using skill-based routing instead.",
     "ivr"),

    # --- routing ---
    ("How does skill-based routing work?",
     "Skill-based routing matches incoming calls to agents tagged with the relevant skill "
     "(e.g., 'billing', 'technical-support'). Configure skills under Admin Console > Agents > "
     "Skills, then assign skills to queues under Queue Settings > Routing Method.",
     "routing"),

    ("Why are calls not being distributed evenly across my agents?",
     "By default, CloudDesk uses longest-idle-agent routing, which can appear uneven over "
     "short time windows but balances out over a full day. If you need strictly even "
     "distribution, switch to round-robin routing under Queue Settings > Routing Method.",
     "routing"),

    ("Why are calls dropping before reaching an agent?",
     "Dropped calls before agent connection are usually caused by queue timeout settings set "
     "too low, or no available agents with the required skill. Check Queue Settings > Timeout "
     "Behavior and confirm enough agents are logged in and available during the affected hours.",
     "routing"),

    ("How do I prioritize VIP customers in the call queue?",
     "Enterprise plans support priority queueing. Tag VIP accounts under Account Tags, then "
     "enable 'Priority Queue Position' under Queue Settings. Tagged customers will be placed "
     "ahead of standard callers in the same queue.",
     "routing"),

    # --- integration ---
    ("How do I connect Salesforce to CloudDesk?",
     "Go to Admin Console > Integrations > Salesforce > Connect, and sign in with a Salesforce "
     "admin account to authorize the connection. Once connected, customer records sync "
     "automatically every 15 minutes. A manual sync option is also available.",
     "integration"),

    ("Why did my Salesforce sync stop working?",
     "Sync failures are most commonly caused by an expired Salesforce authorization token. "
     "Go to Admin Console > Integrations > Salesforce and click Reconnect. If the issue "
     "persists, check that your Salesforce admin account still has API access enabled.",
     "integration"),

    ("How do I generate an API key for a custom integration?",
     "Account owners and admins can generate API keys under Admin Console > Integrations > "
     "API Keys > Generate New Key. Each key can be scoped to specific permissions. Keep your "
     "key secure -- it will only be shown once at creation time.",
     "integration"),

    ("Why is my HubSpot integration creating duplicate contacts?",
     "Duplicates usually occur when contact matching is configured to use name instead of "
     "email. Go to Integrations > HubSpot > Field Mapping and set the matching key to Email "
     "Address to prevent duplicate contact creation.",
     "integration"),

    ("How do I set up webhook notifications?",
     "Go to Admin Console > Integrations > Webhooks > Add Endpoint, and provide the URL you'd "
     "like CloudDesk to send event data to. You can select which events trigger a webhook "
     "(e.g., new ticket created, call completed) under Event Subscriptions.",
     "integration"),

    # --- account ---
    ("Why was my account locked?",
     "Accounts are locked automatically after a failed payment retry, or manually by our "
     "billing team in cases of suspected fraud. To unlock your account, resolve any "
     "outstanding payment issue under Account > Billing, or contact support if you believe "
     "this was done in error.",
     "account"),

    ("How do I transfer account ownership to someone else?",
     "Only the current account owner can transfer ownership. Go to Account > Team Members, "
     "select the new owner from your existing admins, and confirm the transfer. The previous "
     "owner is automatically downgraded to admin role.",
     "account"),

    ("How do I change a team member's role?",
     "Account owners and admins can change roles under Account > Team Members > select the "
     "member > Edit Role. Note that only the account owner can promote someone else to the "
     "owner role, and doing so automatically demotes the current owner.",
     "account"),

    ("How do I cancel my subscription?",
     "Only the account owner can cancel a subscription. Go to Account > Billing > Cancel "
     "Subscription. Cancellation takes effect at the end of your current billing period; "
     "your account will retain access until that date.",
     "account"),

    ("How do I add a new team member to my account?",
     "Account owners and admins can invite new members under Account > Team Members > Invite "
     "Member. Enter their email and select a role (admin or member). They'll receive an "
     "email invitation to set up their login.",
     "account"),

    # --- agent_desktop ---
    ("Why can't my support agent see customer history in the desktop view?",
     "This is usually a permissions issue. Confirm the agent's role has 'View Customer "
     "History' enabled under Admin Console > Agents > Permissions. If permissions are "
     "correct, try having the agent log out and back in to refresh their session.",
     "agent_desktop"),

    ("Why does the agent desktop log users out randomly?",
     "Unexpected logouts are most often caused by session timeout settings being too short, "
     "or multiple simultaneous logins on the same account. Check Admin Console > Security > "
     "Session Settings, and confirm the agent isn't logged in on more than one device.",
     "agent_desktop"),

    ("How do I reset an agent's password?",
     "Account owners and admins can reset a team member's password under Account > Team "
     "Members > select the member > Reset Password. The member will receive an email link "
     "to set a new password; the link expires after 24 hours.",
     "agent_desktop"),

    ("Why is the screen pop showing the wrong customer record?",
     "Screen pop matches incoming calls to customer records using caller ID phone number. If "
     "a customer has multiple records with different phone numbers, or the wrong number is "
     "on file, you may need to update their phone number under Customer Records.",
     "agent_desktop"),
]


def load_articles(conn):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM knowledge_base_articles;")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'knowledge_base_articles';")

    cursor.executemany("""
        INSERT INTO knowledge_base_articles (title, content, category)
        VALUES (?, ?, ?)
    """, KB_ARTICLES)
    conn.commit()
    print(f"✅ Loaded {len(KB_ARTICLES)} knowledge base articles.")


if __name__ == "__main__":
    connection = sqlite3.connect(DB_NAME)
    load_articles(connection)
    connection.close()
