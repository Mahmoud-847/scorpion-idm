# Privacy Policy — Scorpion IDM Integration Module

Publisher: **Scorpion Labs**  
Effective date: **8 November 2026**

This policy describes the **Scorpion IDM Integration Module** extension for **Microsoft Edge** and its communication with the Scorpion IDM desktop application on your Windows computer.

## Purpose and data use

The extension identifies downloadable media in webpages and sends downloads you choose, or browser downloads captured when automatic interception is enabled, to the desktop application. Reading available video qualities also contacts that application. It does not create a Scorpion account or operate an analytics or advertising service.

The extension accesses the following information only to provide these features:

| Information | Use and destination |
| --- | --- |
| Page, frame, media and download URLs; referrers; page/media titles; filenames; selected quality; duration and size | Identify the selected media, list qualities and name or download the file. Relevant values are sent to the local desktop application. URLs can contain private identifiers or access tokens. |
| Media request URLs and response metadata, such as content type | Recognize media streams, including streams without filename extensions. A bounded, temporary list is kept in extension memory for each tab and cleared on navigation or closing the tab. |
| Cookies associated with the relevant download, media, page or candidate-source sites | Allow the local desktop application to retrieve media you can access while signed in. These cookies may include authentication/session values. The extension does not send a copy of your entire cookie store. Relevant cookies can be forwarded when a download is captured or requested, or when qualities are requested. |
| Selected Telegram media bytes | Read the selected video's data through the Telegram webpage session and pass chunks to the local application to save the file. The source remains bound to that download while you scroll. The tab must remain open. |
| Extension preferences | Store language, download interception, floating-button visibility and the minimum file-size preference in local extension storage. |
| Temporary transfer ownership and the latest error code | Associate transfers with their originating tab/frame and display useful feedback in the extension popup. Session storage is used; error records contain a fixed code and time, not raw error text, URLs or cookies. |
| Browser type and connection/language information | Check whether the desktop application is available and synchronize the chosen language with it. |

The extension does not intentionally read password fields, collect payment details, or keep a general browsing-history database. However, a selected URL, title, filename or site cookie may itself contain personal or sensitive information. Only download content you intend the desktop application to access.

## Local communication and external services

Extension-to-application communication uses the loopback address `http://127.0.0.1:19615` on your computer. It is local communication, not a Scorpion cloud upload, and is not encrypted by TLS. Cookies and media data are not sent to a Scorpion-operated remote server. Scorpion Labs does not sell this data or share it for advertising, analytics or profiling.

To fetch a file or inspect available formats, the desktop application contacts the original website and any media/CDN endpoints needed for that content. Those services receive the network requests and relevant request information, including applicable site cookies when needed. Their own privacy policies apply. The desktop application's update and component-download features may contact GitHub and the relevant component providers; these requests reveal ordinary network information such as your IP address. Download history and site cookies are not intentionally uploaded as update telemetry.

Opening this policy or the support page on GitHub contacts GitHub. Microsoft Edge and the Microsoft Edge Add-ons website also have their own privacy practices, separate from this extension.

## Storage and retention

Extension preferences remain in your local browser profile until you change them or remove the extension. Captured media metadata in memory and transfer-reader sessions are temporary. Reader sessions expire after inactivity or are released when a transfer ends. Transfer ownership and the latest error code use browser session storage, which is cleared when the browser session ends; the popup hides errors older than one hour and lets you dismiss them sooner.

The desktop application stores download records, source URLs, filenames, paths, settings and downloaded files locally. Those records and files remain until you remove them; uninstalling the extension does not delete desktop application data or saved downloads. The application may keep relevant site cookies in memory and write a temporary cookie file while extracting/downloading media. It attempts to delete that file after the task finishes. A crash or failed cleanup can leave temporary files on disk. Local data is not represented as encrypted storage.

## Your choices, access and deletion

- In the extension popup, turn off automatic interception and/or the floating video button. These switches control their respective features; they do not disable every extension function or explicitly requested download.
- In Microsoft Edge's extension settings, limit permitted sites, disable the extension to stop its operation, or remove it. Closing a tab ends browser-dependent transfers; cancel a running transfer in the desktop application when needed.
- Review, cancel or remove download records in the desktop application. Remove saved files separately if you also want the downloaded content deleted.
- For complete local cleanup, close the browser and desktop application, remove the extension, and remove the desktop application's local data and temporary files from `%LOCALAPPDATA%\ScorpionIDM`. This also removes settings and history and may affect unfinished downloads. Saved downloads in other folders must be removed separately.
- There is no Scorpion server-side account or cloud download-history database for us to provide or erase. Data held by a source website or GitHub is controlled by that service.

## Contact and policy changes

For privacy questions, contact Scorpion Labs through the project's [support issue form](https://github.com/Mahmoud-847/scorpion-idm/issues/new). Issues are public: do not include cookies, private video links, access tokens, personal data or download logs containing them. You can ask for a private contact method without posting those details.

We will update this page and its effective date when the extension's data practices change. The current policy is available at this public URL and through the extension popup.
