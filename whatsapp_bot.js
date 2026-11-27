/**
 * Princess of Jannah — 24/7 Live WhatsApp Admin Group Bot
 * Target Group: "Princess of Jannah Posts"
 * Powered by @whiskeysockets/baileys (Multi-Device Engine)
 */

const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    downloadMediaMessage,
    jidNormalizedUser,
    fetchLatestBaileysVersion,
    Browsers
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const qrcode = require('qrcode-terminal');
const { execFile } = require('child_process');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

const AUTH_FOLDER = path.join(__dirname, 'auth_info_baileys');
const TEMP_DIR = path.join(__dirname, 'temp_media');
const LOG_FILE = path.join(__dirname, 'bot.log');
const GROUP_JID_FILE = path.join(__dirname, 'matched_group_jid.txt');
const PROCESSED_WA_FILE = path.join(__dirname, 'data', 'processed_wa_msgs.json');

function loadProcessedMsgIds() {
    try {
        if (fs.existsSync(PROCESSED_WA_FILE)) {
            return new Set(JSON.parse(fs.readFileSync(PROCESSED_WA_FILE, 'utf-8')));
        }
    } catch (e) {}
    return new Set();
}

function saveProcessedMsgIds(setObj) {
    try {
        fs.mkdirSync(path.dirname(PROCESSED_WA_FILE), { recursive: true });
        fs.writeFileSync(PROCESSED_WA_FILE, JSON.stringify([...setObj], null, 2), 'utf-8');
    } catch (e) {}
}

const processedMsgIds = loadProcessedMsgIds();
let ingestionSerialQueue = Promise.resolve();

function runSequentially(fn) {
    ingestionSerialQueue = ingestionSerialQueue.then(fn).catch(err => log(`[SERIAL ERR] ${err.message || err}`));
    return ingestionSerialQueue;
}

function execPythonPromise(args, timeoutMs = 600000) {
    return new Promise((resolve) => {
        execFile('python', args, { timeout: timeoutMs }, (error, stdout, stderr) => {
            resolve({ error, stdout: stdout || '', stderr: stderr || '' });
        });
    });
}

const TARGET_GROUP_JID = (process.env.WHATSAPP_ADMIN_GROUP_ID || '').trim();
const allowedGroupJids = new Set(TARGET_GROUP_JID ? [TARGET_GROUP_JID] : []);

if (!fs.existsSync(TEMP_DIR)) {
    fs.mkdirSync(TEMP_DIR, { recursive: true });
}

function log(msg) {
    const timestamp = new Date().toISOString();
    const str = `[${timestamp}] ${typeof msg === 'object' ? JSON.stringify(msg) : msg}`;
    console.log(str);
    try {
        fs.appendFileSync(LOG_FILE, str + '\n');
    } catch (e) {}
}

async function sendSafeMessage(sock, jid, content, quoted) {
    try {
        return await sock.sendMessage(jid, content, { quoted });
    } catch (err) {
        log(`[WARN] Quoted send failed (${err.message}), falling back to direct send`);
        try {
            return await sock.sendMessage(jid, content);
        } catch (err2) {
            log(`[ERROR] Direct send failed completely: ${err2.message}`);
        }
    }
}

function extractText(msg) {
    if (!msg || !msg.message) return '';
    let m = msg.message;
    if (m.ephemeralMessage) m = m.ephemeralMessage.message || m;
    if (m.viewOnceMessage) m = m.viewOnceMessage.message || m;
    if (m.viewOnceMessageV2) m = m.viewOnceMessageV2.message || m;
    if (m.documentWithCaptionMessage) m = m.documentWithCaptionMessage.message || m;

    return (
        m.conversation ||
        m.extendedTextMessage?.text ||
        m.imageMessage?.caption ||
        m.videoMessage?.caption ||
        m.documentMessage?.caption ||
        ''
    ).trim();
}

function isTargetAdminGroup(rawSubject) {
    if (!rawSubject) return false;
    const clean = rawSubject
        .replace(/[^\p{L}\p{N}\s]/gu, '')
        .replace(/\s+/g, ' ')
        .trim()
        .toLowerCase();

    const envTarget = (process.env.WHATSAPP_ADMIN_GROUP_NAME || 'princess of jannah posts')
        .replace(/[^\p{L}\p{N}\s]/gu, '')
        .replace(/\s+/g, ' ')
        .trim()
        .toLowerCase();

    return (
        clean === envTarget ||
        clean === 'princess of jannah posts' ||
        clean === 'princess of jannah post'
    );
}

function recordMatchedGroupJid(jid, subject) {
    allowedGroupJids.add(jid);
    try {
        fs.writeFileSync(GROUP_JID_FILE, jid, 'utf-8');
    } catch (e) {}
    log(`[WHITELIST LOCKED] Matched Admin Group: "${subject}" -> ${jid}`);
}

async function refreshAllowedGroups(sock) {
    try {
        const groups = await sock.groupFetchAllParticipating();
        for (const [jid, data] of Object.entries(groups)) {
            if (isTargetAdminGroup(data.subject)) {
                recordMatchedGroupJid(jid, data.subject);
            }
        }
    } catch (e) {
        log(`[WHITELIST ERROR] ${e.message}`);
    }
}

function extractCardFromOutput(stdout) {
    if (!stdout) return '';
    const lines = stdout.split(/\r?\n/);
    const cardIndex = lines.findIndex(l => l.includes('*PRINCESS OF JANNAH'));
    return (cardIndex !== -1 ? lines.slice(cardIndex).join('\n') : stdout).trim();
}

let currentSock = null;
let reconnectTimer = null;

function scheduleReconnect(delayMs = 5000) {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        startWhatsAppBot().catch(err => log(`[!] Reconnect error: ${err.message}`));
    }, delayMs);
}

process.on('uncaughtException', (err) => {
    log(`[GUARD] Caught exception (${err.message || err}). Keeping daemon alive...`);
    if (String(err.message || err).includes('Connection Closed')) {
        scheduleReconnect(5000);
    }
});

process.on('unhandledRejection', (reason) => {
    const msg = reason?.message || String(reason);
    log(`[GUARD] Caught unhandled rejection (${msg}). Keeping daemon alive...`);
    if (msg.includes('Connection Closed')) {
        scheduleReconnect(5000);
    }
});

// Single global outgoing queue worker using current active socket
const SEND_QUEUE_FILE = path.join(__dirname, 'send_queue.json');
setInterval(async () => {
    if (!currentSock) return;
    if (fs.existsSync(SEND_QUEUE_FILE)) {
        try {
            const raw = fs.readFileSync(SEND_QUEUE_FILE, 'utf-8');
            const queue = JSON.parse(raw);
            try { fs.unlinkSync(SEND_QUEUE_FILE); } catch (e) {}
            for (const item of queue) {
                if (!item.to) continue;
                log(`[QUEUE SEND] To: ${item.to}, Text: "${(item.text || '').substring(0, 40)}..."`);
                await sendSafeMessage(currentSock, item.to, { text: item.text });
            }
        } catch (e) {
            log(`[QUEUE ERROR] ${e.message}`);
        }
    }
}, 2000);

function purgeStaleSignalSessions() {
    if (!fs.existsSync(AUTH_FOLDER)) return;
    try {
        const files = fs.readdirSync(AUTH_FOLDER);
        let removed = 0;
        for (const f of files) {
            if (f.startsWith('sender-key-') || f.startsWith('session-')) {
                try {
                    fs.unlinkSync(path.join(AUTH_FOLDER, f));
                    removed++;
                } catch (e) {}
            }
        }
        if (removed > 0) {
            log(`[SIGNAL HEAL] Purged ${removed} stale Signal session/sender-key files (creds preserved).`);
        }
    } catch (e) {}
}

async function startWhatsAppBot() {
    if (currentSock) {
        try {
            log('[CLEANUP] Closing previous socket before reconnecting...');
            currentSock.ws.close();
            currentSock.ev.removeAllListeners();
        } catch (e) {}
        currentSock = null;
    }

    log('Initializing Princess of Jannah WhatsApp Engine...');
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_FOLDER);
    const { version, isLatest } = await fetchLatestBaileysVersion();
    log(`[*] Using WhatsApp Web v${version.join('.')} (isLatest: ${isLatest})`);

    const sock = makeWASocket({
        version,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false,
        auth: state,
        browser: Browsers.ubuntu('Chrome'),
        keepAliveIntervalMs: 15000,
        emitOwnEvents: true,
        defaultQueryTimeoutMs: 60000,
        connectTimeoutMs: 60000,
        syncFullHistory: false,
        shouldSyncHistoryMessage: () => true,
        markOnlineOnConnect: true,
        getMessage: async () => ({ conversation: '' })
    });
    currentSock = sock;

    sock.ev.on('creds.update', saveCreds);

    let heartbeatTimer = null;
    let bufferFlushTimer = null;

    // Fix for @whiskeysockets/baileys v6.7.24 event-buffer bug:
    // createBufferedFunction() activates ev.buffer() during offline/app-state sync without
    // flushing in finally{}, trapping incoming messages.upsert in RAM forever unless flushed.
    bufferFlushTimer = setInterval(() => {
        try {
            if (sock?.ev && typeof sock.ev.isBuffering === 'function' && sock.ev.isBuffering()) {
                sock.ev.flush();
            }
        } catch (e) {}
    }, 800);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            log('NEW QR CODE GENERATED — Scan in terminal or open /qr in browser');
            qrcode.generate(qr, { small: true });

            try {
                fs.writeFileSync(path.join(__dirname, 'qr_code.txt'), qr, 'utf-8');
                fs.writeFileSync(path.join(__dirname, 'bot_status.txt'), 'WAITING_QR', 'utf-8');
            } catch (e) {}
        }

        if (connection === 'close') {
            if (heartbeatTimer) clearInterval(heartbeatTimer);
            if (bufferFlushTimer) clearInterval(bufferFlushTimer);
            const statusCode = (lastDisconnect?.error)?.output?.statusCode;
            log(`[!] Connection closed. Reason: ${lastDisconnect?.error}. StatusCode: ${statusCode}`);
            try {
                fs.writeFileSync(path.join(__dirname, 'bot_status.txt'), 'RECONNECTING', 'utf-8');
            } catch (e) {}

            try {
                sock.ws.close();
                sock.ev.removeAllListeners();
            } catch (e) {}

            if (statusCode === DisconnectReason.loggedOut) {
                log('[!] Logged out permanently. Resetting credentials...');
                try { fs.rmSync(AUTH_FOLDER, { recursive: true, force: true }); } catch (e) {}
            }

            scheduleReconnect(5000);
        } else if (connection === 'open') {
            log('[SUCCESS] Princess of Jannah WhatsApp Bot is CONNECTED!');
            log(`Bot JID: ${jidNormalizedUser(sock.user.id)}`);

            try {
                fs.writeFileSync(path.join(__dirname, 'bot_status.txt'), 'CONNECTED', 'utf-8');
                const qrPath = path.join(__dirname, 'qr_code.txt');
                if (fs.existsSync(qrPath)) fs.unlinkSync(qrPath);
            } catch (e) {}

            await refreshAllowedGroups(sock);

            // Optional one-time recovery of videos/links when explicitly requested via env
            const targetGroupJid = TARGET_GROUP_JID || [...allowedGroupJids][0] || '120363413927212088@g.us';
            if (process.env.RUN_INITIAL_HISTORY_RECOVERY === 'true' && !fs.existsSync(PROCESSED_WA_FILE) && targetGroupJid) {
                setTimeout(async () => {
                    try {
                        log(`[HISTORY RECOVERY] Requesting last 50 messages of ${targetGroupJid} from primary phone...`);
                        const anchor = await sock.sendMessage(targetGroupJid, {
                            text: '*PRINCESS OF JANNAH*\nAna duba bidiyoyi da links da aka turo a wannan rukunin don sakawa a gaba...'
                        });
                        if (anchor?.key) {
                            processedMsgIds.add(anchor.key.id);
                            saveProcessedMsgIds(processedMsgIds);
                            await sock.fetchMessageHistory(50, anchor.key, Date.now());
                            log(`[HISTORY RECOVERY] Sent on-demand history request using anchor ${anchor.key.id}`);
                        }
                    } catch (e) {
                        log(`[HISTORY RECOVERY WARN] ${e.message}`);
                    }
                }, 3500);
            }

            if (heartbeatTimer) clearInterval(heartbeatTimer);
            heartbeatTimer = setInterval(() => {
                sock.sendPresenceUpdate('available').catch(() => {});
            }, 20000);
        }
    });

    // Outgoing Message Queue listener (triggered via /send-test or web dashboard)
    // Managed at top-level with currentSock to prevent duplicate intervals on reconnection

    async function processTargetGroupMessage(msg, isHistoryRecovery = false) {
        if (!msg || !msg.key || !msg.message) return;
        const from = msg.key.remoteJid || 'unknown';
        const msgId = msg.key.id || '';

        let isAllowed = allowedGroupJids.has(from);
        if (!isAllowed && from.endsWith('@g.us') && !isHistoryRecovery) {
            try {
                const meta = await sock.groupMetadata(from);
                if (meta && isTargetAdminGroup(meta.subject)) {
                    recordMatchedGroupJid(from, meta.subject);
                    isAllowed = true;
                }
            } catch (e) {}
        }
        if (!isAllowed) return;

        if (msgId && processedMsgIds.has(msgId)) {
            return;
        }

        const text = extractText(msg);
        if (
            text.startsWith('*PRINCESS OF JANNAH') ||
            text.startsWith('*ALHAMDULILLAH!') ||
            text.startsWith('An karɓi bidiyo daga') ||
            text.startsWith('An karɓi link daga')
        ) {
            if (msgId) {
                processedMsgIds.add(msgId);
                saveProcessedMsgIds(processedMsgIds);
            }
            return;
        }

        const sender = msg.key.participant || msg.key.remoteJid;
        const senderPhone = '@' + sender.split('@')[0];
        const upperText = text.toUpperCase();

        // Only run interactive text commands on live messages (not historical replay)
        if (!isHistoryRecovery) {
            if (['PING', 'STATUS', 'QUEUE', 'TEST', 'HI', 'HELLO', 'SALAM'].includes(upperText)) {
                if (msgId) { processedMsgIds.add(msgId); saveProcessedMsgIds(processedMsgIds); }
                const { stdout } = await execPythonPromise(['whatsapp_pipeline.py', '--status', '--phone', senderPhone], 30000);
                const card = extractCardFromOutput(stdout) || `*PRINCESS OF JANNAH — BOT ONLINE*\n\nAssalamu Alaikum ${senderPhone}, Bot yana aiki 100%!`;
                await sendSafeMessage(sock, from, { text: card, mentions: [sender] }, msg);
                return;
            }
            if (['ANALYTICS', 'REPORT', 'STATS', 'GROWTH'].includes(upperText)) {
                if (msgId) { processedMsgIds.add(msgId); saveProcessedMsgIds(processedMsgIds); }
                const { stdout } = await execPythonPromise(['whatsapp_pipeline.py', '--analytics', '--phone', senderPhone], 45000);
                const card = extractCardFromOutput(stdout) || `*PRINCESS OF JANNAH*\n\nAssalamu Alaikum ${senderPhone}, ana duba kididdigar Facebook...`;
                await sendSafeMessage(sock, from, { text: card, mentions: [sender] }, msg);
                return;
            }
            if (['PUBLISH NOW', 'POST NOW', 'PUBLISH'].includes(upperText)) {
                if (msgId) { processedMsgIds.add(msgId); saveProcessedMsgIds(processedMsgIds); }
                const { stdout, stderr } = await execPythonPromise(['engine.py', 'publish'], 300000);
                const out = (stdout || stderr || '').trim();
                const reply = `*PRINCESS OF JANNAH*\n\nAssalamu Alaikum ${senderPhone},\nSakamakon wallafawa kai tsaye:\n\`\`\`${out.slice(-400)}\`\`\``;
                await sendSafeMessage(sock, from, { text: reply, mentions: [sender] }, msg);
                return;
            }
            if (upperText === 'SYNC') {
                if (msgId) { processedMsgIds.add(msgId); saveProcessedMsgIds(processedMsgIds); }
                await sock.fetchMessageHistory(50, msg.key, Date.now());
                return;
            }
        }

        // Check Direct Video Upload FIRST
        const docMsg = msg.message.documentMessage ||
            msg.message.documentWithCaptionMessage?.message?.documentMessage ||
            msg.message.ephemeralMessage?.message?.documentMessage;
        const isVideoDoc = docMsg && (
            (docMsg.mimetype && docMsg.mimetype.startsWith('video/')) ||
            /\.(mp4|mov|mkv|webm)$/i.test(docMsg.fileName || '')
        );
        const isVideo = msg.message.videoMessage ||
            msg.message.ephemeralMessage?.message?.videoMessage ||
            msg.message.viewOnceMessage?.message?.videoMessage ||
            msg.message.viewOnceMessageV2?.message?.videoMessage ||
            isVideoDoc;

        if (isVideo) {
            if (msgId) { processedMsgIds.add(msgId); saveProcessedMsgIds(processedMsgIds); }
            log(`[+] ${isHistoryRecovery ? '[RECOVERED] ' : ''}Direct video from ${senderPhone} (msgId=${msgId})`);

            if (!isHistoryRecovery) {
                await sendSafeMessage(sock, from, {
                    text: `An karɓi bidiyo daga ${senderPhone}. Ana gyara sauti da shirya shi don Facebook Reels + Story...`,
                    mentions: [sender]
                }, msg);
            }

            try {
                const buffer = await downloadMediaMessage(
                    msg,
                    'buffer',
                    {},
                    {
                        logger: pino({ level: 'silent' }),
                        reuploadRequest: sock.updateMediaMessage
                    }
                );
                const filename = `upload_${Date.now()}_${Math.floor(Math.random() * 1000)}.mp4`;
                const filepath = path.join(TEMP_DIR, filename);
                fs.writeFileSync(filepath, buffer);
                log(`[+] Saved video to ${filepath} (${buffer.length} bytes)`);

                const { error, stdout, stderr } = await execPythonPromise(
                    ['whatsapp_pipeline.py', '--video', filepath, '--phone', senderPhone, '--caption', text],
                    600000
                );
                if (error) log(`[EXEC ERROR] ${error.message} | ${stderr}`);
                const cleanCard = extractCardFromOutput(stdout) || (
                    `*PRINCESS OF JANNAH*\n\nAssalamu Alaikum ${senderPhone},\n✅ An karɓi bidiyo kuma an saka a gaban Queue.`
                );
                await sendSafeMessage(sock, from, { text: cleanCard, mentions: [sender] }, msg);
                log(`[+] Completed video ingestion for msgId=${msgId}`);
            } catch (err) {
                log(`[!] Error downloading video message (${msgId}): ${err.message}`);
            }
            return;
        }

        // Check Shared Links SECOND
        const linkCandidateText = [
            text,
            msg.message?.extendedTextMessage?.canonicalUrl || '',
            msg.message?.extendedTextMessage?.matchedText || ''
        ].join(' ');
        const urlRegex = /(https?:\/\/[^\s]+)/g;
        const urls = (linkCandidateText.match(urlRegex) || []).filter(
            u => !u.includes('facebook.com/reel/') || !text.includes('PRINCESS OF JANNAH')
        );

        if (urls.length > 0) {
            if (msgId) { processedMsgIds.add(msgId); saveProcessedMsgIds(processedMsgIds); }
            const targetUrl = urls[0];
            log(`[+] ${isHistoryRecovery ? '[RECOVERED] ' : ''}Link detected: ${targetUrl} from ${senderPhone} (msgId=${msgId})`);

            if (!isHistoryRecovery) {
                await sendSafeMessage(sock, from, {
                    text: `An karɓi link daga ${senderPhone}. Ana saukewa da shirya shi don Facebook Reels + Story...`,
                    mentions: [sender]
                }, msg);
            }

            const { error, stdout, stderr } = await execPythonPromise(
                ['whatsapp_pipeline.py', '--url', targetUrl, '--phone', senderPhone, '--caption', text],
                600000
            );
            if (error) log(`[EXEC ERROR] ${error.message} | ${stderr}`);
            const cleanCard = extractCardFromOutput(stdout) || (
                `*PRINCESS OF JANNAH*\n\nAssalamu Alaikum ${senderPhone},\n⚠️ An sami matsala wajen sauke wannan link: ${targetUrl}`
            );
            await sendSafeMessage(sock, from, { text: cleanCard, mentions: [sender] }, msg);
            log(`[+] Completed link ingestion for ${targetUrl}`);
            return;
        }

        if (msgId) {
            processedMsgIds.add(msgId);
            saveProcessedMsgIds(processedMsgIds);
        }
    }

    sock.ev.on('messaging-history.set', ({ messages }) => {
        const groupMsgs = (messages || []).filter(m => m?.key?.remoteJid && allowedGroupJids.has(m.key.remoteJid));
        log(`[HISTORY SYNC] Received ${(messages || []).length} total history msg(s); ${groupMsgs.length} in Princess of Jannah Posts.`);
        if (!groupMsgs.length) return;

        // Sort oldest -> newest so earlier shared videos/links post first
        groupMsgs.sort((a, b) => Number(a.messageTimestamp || 0) - Number(b.messageTimestamp || 0));
        // Only recover items from the last 7 days
        const cutoffSec = Math.floor(Date.now() / 1000) - 7 * 86400;
        for (const hm of groupMsgs) {
            const ts = Number(hm.messageTimestamp || 0);
            if (ts > 0 && ts < cutoffSec) continue;
            runSequentially(() => processTargetGroupMessage(hm, true));
        }
    });

    sock.ev.on('messages.upsert', async (m) => {
        for (const msg of (m.messages || [])) {
            try {
                if (!msg) continue;
                const from = msg.key ? msg.key.remoteJid : 'unknown';
                const fromMe = msg.key ? msg.key.fromMe : false;
                const hasMsg = !!msg.message;
                const msgKeys = hasMsg ? Object.keys(msg.message).join(',') : 'NONE';
                const text = extractText(msg);

                log(`[RAW INCOMING] from: ${from}, fromMe: ${fromMe}, msgKeys: [${msgKeys}], stub: ${msg.messageStubType || 'none'}, text: "${text.substring(0, 40)}"`);

                if (allowedGroupJids.has(from) || from.endsWith('@g.us')) {
                    runSequentially(() => processTargetGroupMessage(msg, false));
                }
            } catch (error) {
                log(`[!] Handler error: ${error.message}`);
            }
        }
    });
}

startWhatsAppBot().catch(err => log(`[!] Fatal error starting bot: ${err.message}`));
