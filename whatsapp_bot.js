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
        markOnlineOnConnect: true,
        getMessage: async () => ({ conversation: '' })
    });
    currentSock = sock;

    sock.ev.on('creds.update', saveCreds);

    let heartbeatTimer = null;

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

            if (heartbeatTimer) clearInterval(heartbeatTimer);
            heartbeatTimer = setInterval(() => {
                sock.sendPresenceUpdate('available').catch(() => {});
            }, 20000);
        }
    });

    // Outgoing Message Queue listener (triggered via /send-test or web dashboard)
    // Managed at top-level with currentSock to prevent duplicate intervals on reconnection

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

                // Strict Group Isolation Guard ("Princess of Jannah Posts")
                let isAllowed = allowedGroupJids.has(from);

                if (!isAllowed && from.endsWith('@g.us')) {
                    try {
                        const meta = await sock.groupMetadata(from);
                        if (meta && isTargetAdminGroup(meta.subject)) {
                            recordMatchedGroupJid(from, meta.subject);
                            isAllowed = true;
                        }
                    } catch (e) {}
                }

                if (!isAllowed) {
                    continue;
                }

                if (!hasMsg) {
                    continue;
                }

                const sender = msg.key.participant || msg.key.remoteJid;
                const senderPhone = '@' + sender.split('@')[0];

                // Ignore the bot's own formatted replies to prevent infinite loops
                if (
                    text.startsWith('*PRINCESS OF JANNAH') ||
                    text.startsWith('An karɓi bidiyo daga') ||
                    text.startsWith('An karɓi link daga')
                ) {
                    continue;
                }

                log(`[*] Processing in Princess of Jannah Posts from ${senderPhone}: "${text.substring(0, 60)}"`);

                const upperText = text.toUpperCase();

                // 1. Status / Queue / Ping Check
                if (['PING', 'STATUS', 'QUEUE', 'TEST', 'HI', 'HELLO', 'SALAM'].includes(upperText)) {
                    execFile('python', ['whatsapp_pipeline.py', '--status', '--phone', senderPhone], { timeout: 30000 }, async (err, stdout) => {
                        const card = extractCardFromOutput(stdout) || `*PRINCESS OF JANNAH — BOT ONLINE*\n\nAssalamu Alaikum ${senderPhone}, Bot yana aiki 100%!`;
                        await sendSafeMessage(sock, from, { text: card, mentions: [sender] }, msg);
                        log(`[+] Sent status card to ${senderPhone}`);
                    });
                    continue;
                }

                // 1B. Live Facebook Page Growth & Analytics Report
                if (['ANALYTICS', 'REPORT', 'STATS', 'GROWTH'].includes(upperText)) {
                    execFile('python', ['whatsapp_pipeline.py', '--analytics', '--phone', senderPhone], { timeout: 45000 }, async (err, stdout) => {
                        const card = extractCardFromOutput(stdout) || `*PRINCESS OF JANNAH*\n\nAssalamu Alaikum ${senderPhone}, ana duba kididdigar Facebook...`;
                        await sendSafeMessage(sock, from, { text: card, mentions: [sender] }, msg);
                        log(`[+] Sent analytics growth report to ${senderPhone}`);
                    });
                    continue;
                }

                // 2. Manual "PUBLISH NOW" / "POST NOW" Trigger
                if (['PUBLISH NOW', 'POST NOW', 'PUBLISH'].includes(upperText)) {
                    execFile('python', ['engine.py', 'publish'], { timeout: 300000 }, async (err, stdout, stderr) => {
                        const out = (stdout || stderr || '').trim();
                        const reply = `*PRINCESS OF JANNAH*\n\nAssalamu Alaikum ${senderPhone},\nSakamakon wallafawa kai tsaye:\n\`\`\`${out.slice(-400)}\`\`\``;
                        await sendSafeMessage(sock, from, { text: reply, mentions: [sender] }, msg);
                    });
                    continue;
                }

                // 3. Manual "DISCOVER" Trigger
                if (upperText === 'DISCOVER') {
                    await sendSafeMessage(sock, from, {
                        text: `*PRINCESS OF JANNAH*\n\nAna nemo sabon gajeren bidiyo daga malamai don sakawa a Queue...`,
                        mentions: [sender]
                    }, msg);

                    execFile('python', ['engine.py', 'discover', '--count', '1'], { timeout: 300000 }, () => {
                        execFile('python', ['whatsapp_pipeline.py', '--status', '--phone', senderPhone], { timeout: 30000 }, async (err2, stdout2) => {
                            const card = extractCardFromOutput(stdout2);
                            if (card) {
                                await sendSafeMessage(sock, from, { text: card, mentions: [sender] }, msg);
                            }
                        });
                    });
                    continue;
                }

                // 4. Shared Link Detection (Facebook, YouTube Shorts, Instagram, TikTok, etc.)
                const urlRegex = /(https?:\/\/[^\s]+)/g;
                const urls = text.match(urlRegex);

                if (urls && urls.length > 0) {
                    const targetUrl = urls[0];
                    log(`[+] Link detected: ${targetUrl} from ${senderPhone}`);

                    await sendSafeMessage(sock, from, {
                        text: `An karɓi link daga ${senderPhone}. Ana saukewa da sakawa a Queue...`,
                        mentions: [sender]
                    }, msg);

                    execFile(
                        'python',
                        ['whatsapp_pipeline.py', '--url', targetUrl, '--phone', senderPhone, '--caption', text],
                        { timeout: 600000 },
                        async (error, stdout, stderr) => {
                            if (error) {
                                log(`[EXEC ERROR] ${error.message} | ${stderr}`);
                            }
                            const cleanCard = extractCardFromOutput(stdout) || (
                                `*PRINCESS OF JANNAH*\n\nAssalamu Alaikum ${senderPhone},\n⚠️ An sami matsala wajen sauke wannan link: ${targetUrl}`
                            );
                            await sendSafeMessage(sock, from, {
                                text: cleanCard,
                                mentions: [sender]
                            }, msg);
                            log(`[+] Sent auto-queue confirmation card for ${targetUrl}`);
                        }
                    );
                    continue;
                }

                // 5. Direct Video Upload Detection
                const isVideo = msg.message.videoMessage ||
                    msg.message.ephemeralMessage?.message?.videoMessage ||
                    msg.message.viewOnceMessage?.message?.videoMessage ||
                    msg.message.viewOnceMessageV2?.message?.videoMessage;

                if (isVideo) {
                    log(`[+] Direct video uploaded by ${senderPhone}`);

                    await sendSafeMessage(sock, from, {
                        text: `An karɓi bidiyo daga ${senderPhone}. Ana sakawa a Queue...`,
                        mentions: [sender]
                    }, msg);

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

                        const filename = `upload_${Date.now()}.mp4`;
                        const filepath = path.join(TEMP_DIR, filename);
                        fs.writeFileSync(filepath, buffer);
                        log(`[+] Saved video to ${filepath} (${buffer.length} bytes)`);

                        execFile(
                            'python',
                            ['whatsapp_pipeline.py', '--video', filepath, '--phone', senderPhone, '--caption', text],
                            { timeout: 120000 },
                            async (error, stdout, stderr) => {
                                if (error) {
                                    log(`[EXEC ERROR] ${error.message} | ${stderr}`);
                                }
                                const cleanCard = extractCardFromOutput(stdout) || (
                                    `*PRINCESS OF JANNAH*\n\nAssalamu Alaikum ${senderPhone},\n✅ An karɓi bidiyo kuma an saka a Queue.`
                                );
                                await sendSafeMessage(sock, from, {
                                    text: cleanCard,
                                    mentions: [sender]
                                }, msg);
                                log(`[+] Sent auto-queue confirmation card for direct video`);
                            }
                        );
                    } catch (err) {
                        log(`[!] Error downloading video message: ${err.message}`);
                    }
                    continue;
                }

            } catch (error) {
                log(`[!] Handler error: ${error.message}`);
            }
        }
    });
}

startWhatsAppBot().catch(err => log(`[!] Fatal error starting bot: ${err.message}`));
