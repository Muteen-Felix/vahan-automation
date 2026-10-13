# VAHAN Automation User Guide

This guide is for people using the website for the first time. Button and page names match the interface so you can follow each step easily.

VAHAN Automation helps you collect, view, and download vehicle registration reports from VAHAN by manufacturer, location, and month.

## 1. Getting started

You will need:

- The website address provided by your service provider.
- A username and password provided by your administrator.
- A computer with a web browser and an Internet connection.

Open the website to use the service. You do not need to install the project on your computer.

### Sign in

1. Open the website address you received.
2. Enter your username in **Username**.
3. Enter your password in **Password**.
4. Click **Sign in**.

After signing in, you will see **Exported Reports**.

If you have forgotten your password or do not have an account, contact your administrator.

### What can you access?

| Account type | Available features |
| --- | --- |
| Report viewer — Workspace member | View, search, and download Excel reports; change your own password. |
| Administrator | All report viewer features, plus create filters, schedule report collection, view run history, and manage accounts. |

If you only see **Exported Reports**, start with sections 2 and 3. This is the usual view for a report viewer account.

## 2. Viewing and searching reports

### View the data

1. Click **Exported Reports** in the menu.
2. Select the reporting year in **Year**.
3. If **Report filters** is available, select the report you need. This field appears only when multiple report sets are available.
4. Read the table. Scroll horizontally to see all 12 months.
5. Click **Next** to move to the next page or **Previous** to go back.

The table shows up to 100 rows per page.

| Column | Meaning |
| --- | --- |
| STATE | State or region in India. |
| RTO | Vehicle registration office. |
| RTOCode | Vehicle registration office code. |
| Maker | Vehicle manufacturer. |
| JAN to DEC | Registration counts from January to December. |

**Reading the values:** `0` means zero registrations. A dash (`—`) in a month column means no data is available for that cell. Do not treat a dash as zero.

**Last updated** shows when the data was last updated. **Months with data** shows which months have data in the selected report set; it does not mean every location has been fully collected.

### Search by location

1. Enter a state name in **Search State**.
2. To narrow the results, enter an office name or code in **Search RTO / code**.
3. Wait for the table to update.
4. Click **Clear** to remove the search conditions and view the selected report set again.

For example, to find one registration office, select the year, enter its state in **Search State**, then enter the office code you were given in **Search RTO / code**.

If the table is empty, click **Clear**, check the year and **Report filters**, then click **Refresh**. A new installation has no report data until an administrator collects reports.

## 3. Downloading Excel reports

### Download your search results

1. Select the year and report set you need.
2. Enter your conditions in **Search State** or **Search RTO / code**.
3. Click **Export filtered to Excel**.
4. Read the row count in the confirmation message. Click **OK** to download or **Cancel** to go back.
5. Wait for the download to finish, then open the file from your browser's download folder.

The Excel file includes **all rows matching your search**, including rows on other pages.

### Download the entire selected report

1. Click **Clear** if a State/RTO search is active.
2. Check **Year** and **Report filters**, if shown.
3. Click **Export all to Excel**.
4. Check the row count and click **OK** to confirm.

“All” means all rows in the selected report set and year. When the button shows **Exporting…**, wait for the download to finish before clicking again.

## 4. Password, time zone, and sign-out

### Open your account settings

- Report viewers: click **Account** at the top of the page.
- Administrators: open **Settings**, then click **Account**.

### Change your password

1. In **Account settings**, open **Change password** if tabs are shown.
2. Enter your current password in **Current password**.
3. Enter a new password in **New password**. Use at least 12 characters.
4. Enter the same new password in **Confirm new password**.
5. Click **Update password** and wait for the success message.

Changing your password signs your account out on other devices.

### Select a time zone

In **Account**, choose **Display time zone**:

- **Vietnam time (UTC+07:00)** for Vietnam time.
- **India time (UTC+05:30)** for India time.

For administrators, changing this setting also updates the time zone of saved schedules. Check the scheduled start times in **Settings** after changing it.

### Sign out

Open **Account** and click **Log out**. If the website asks you to sign in again after a period of inactivity, enter your account details to continue.

## 5. Creating report filters — administrators

Saved filters describe the reports you want to collect, such as the year, state, registration office, vehicle category, and fuel type.

### Create new filters

1. Open **Filters**.
2. Click **New filters**.
3. Enter a clear **Filter name**, for example, “Electric two-wheelers — 2026”.
4. Select the report year in **From** or **To**. Both fields currently select the same year; they do not define a range of years.
5. Wait for the choices from VAHAN to load.
6. Open each field you want to change, search for the choices you need, and select them.
7. Click **Save filters** to save, or **Save & preview** to save and preview the reports to be collected.

**Check the default choices before saving.** New filters already include some choices for two-wheelers and electric fuel types. Change these if you need different reports.

| Common field | What to select |
| --- | --- |
| State / RTO | State and registration office. Select State first, then check RTO again. |
| Maker | Vehicle manufacturer. |
| Category Group / Sub-Category / Class | Vehicle group, subgroup, and class. Select the broader group first. |
| EV Type / Fuel | Electric vehicle type and fuel. Check Fuel again after changing EV Type. |
| Active / Archive Type | Active or archived record groups. |

Some choices depend on other fields and may change when you make a selection. Review them before saving.

### Selecting multiple choices

For fields with **Collect reports using**:

- **Selected choices together** uses the selected values together in one filter condition.
- **Each choice separately** collects reports separately for each value. For example, selecting two states means each state is processed separately.

With **Each choice separately**, leaving the selection empty means using all available choices. For your first run, select a small scope and preview it to understand how much work it will create.

**Save & preview** previews the plan; it does not start report collection. After saving, create a schedule using section 6.

To edit filters, select their name under **Saved filters**, make your changes, and save. To delete them, click **Delete** and read the confirmation message. Collected report data is kept.

## 6. Scheduling report collection — administrators

### Create a schedule

1. Open **Settings**.
2. Under **Automatic report schedule**, click **Show form**.
3. Choose your filters in **Saved filters**.
4. Set **Start date** and **Start time**. For your first schedule, choose a time in the near future so you can review it before it starts.
5. Check the time zone shown at the bottom of the form.
6. Choose **Repeat**. Select **Once** for a single run, or **Every month** to repeat on the same day and time each month.
7. Click **Add schedule**.
8. Check the new entry under **Saved schedules**, especially **Next start**.

The report year comes from the saved filters. The date you run collection can be different from the year of the data you are collecting.

For monthly schedules, if a month does not have the selected day, the run starts on that month's last day. For example, a schedule for day 31 runs on the last day of February. After the report year finishes, an enabled monthly schedule automatically creates separate filters and a schedule for the next year. Disable future runs if you do not want collection to continue each year.

### Pause, continue, or disable a schedule

| Button | What it does |
| --- | --- |
| Pause run | Pauses the current run. Work already assigned finishes first, so Pausing may appear for a while. |
| Continue run | Continues the unfinished work in a paused run. |
| Disable future runs | Disables future starts. A run already in progress continues. |
| Enable schedule | Enables future starts again. |
| Delete schedule | Deletes the schedule and unfinished work. Collected data is kept. The button is available only when the run's status allows it. |

To pause the current run and prevent future starts, click **Pause run**, then **Disable future runs**.

You can close the browser tab after saving a schedule. Collection runs on the system, and the server must remain running. If no report collection browser is available, the schedule waits.

## 7. Checking results — administrators

Open **Run History** to see past and current runs, with the newest first. Click **Refresh history** to update immediately.

A “case” is one collection task for a combination of filter choices. **Progress** shows processed tasks out of the total. Processed tasks can include failed tasks.

| Status | Meaning and next step |
| --- | --- |
| Preparing / Resuming | The system is preparing or resuming work. Wait for it to continue. |
| Running | Report collection is in progress. |
| Pausing / Paused | The run is pausing or has paused. Use Continue run in Settings to resume. |
| Completed | The run has finished. |
| Completed with errors | The run has ended with some failed tasks. Check Failed and the messages in Settings. |
| Error | A problem needs attention. Send the error message to support. |
| Stopped | The run has stopped. |

Under **Results**:

- **With data** means the task returned data.
- **No data** means the source had no records for those conditions; this is not a download failure.
- **Failed** means the task encountered an error.

Saved data appears in **Exported Reports**. Seeing some data does not mean the entire run has finished. The system may automatically retry unfinished tasks. Check the current run before creating a duplicate schedule.

## 8. Managing accounts — administrators

1. Open **Settings → Account → Manage user accounts**.
2. Enter **Username** and **Password**. Use a password with at least 12 characters.
3. Click **Create account**.
4. Check the account's role in the list and share the sign-in details privately with the user.

Available account actions:

- **Reset password** sets a new password when a user forgets theirs. Enter and confirm the new password, then click **Save new password**.
- **Disable / Enable** blocks or restores sign-in access.
- **Make administrator** grants administrator access.
- **Make report viewer** changes the account to report viewing and download access.

Grant administrator access only to people responsible for filters, schedules, or user accounts.

## 9. Troubleshooting

| Problem | What to do |
| --- | --- |
| Cannot sign in | Check your username, password, and Caps Lock. If it still fails, ask your administrator to check your account or reset your password. |
| Could not connect or a connection warning | Check your Internet connection, wait for it to return, then reload the page. Contact support if the problem continues. |
| Filters, Settings, or Run History is missing | Your account has report viewer access. Ask your administrator for additional access if your work requires it. |
| No data is shown | Click Clear, check Year and Report filters, then Refresh. If no reports have been collected, ask your administrator to schedule collection. |
| The Excel export button is disabled | Wait for the table to finish loading and check that there are rows matching your search. |
| You clicked download but cannot find the file | Wait for Exporting… to finish and check your browser's download list. Send any error message to support. |
| Filter choices are waiting or cannot be edited | Wait for the current collection run to finish or a report collection browser to become available. Contact support if the wait continues. |
| A schedule has not started at the expected time | Check the time zone, whether the schedule is enabled, and the messages in Settings. The system may be waiting for a report collection browser. |
| Website check / Cannot start yet | In Settings, open Website check if a warning is shown. Click Copy all issues or Copy for support and send the details to support. Wait for the issue to be resolved before continuing. |

When contacting support, include the page name, the time the problem occurred, what you were doing, the filter or schedule name or run number if available, and the error message. Include a screenshot if helpful. **Do not send your password.**

## 10. Your daily workflow

**Report viewers:** sign in → select the year and report set → search by State/RTO → check the data → download Excel → sign out.

**Administrators:** create and review filters → schedule collection → monitor Run History → check data in Exported Reports → create accounts for people who need reports.
