const systemMode = document.getElementById("systemMode");
const enrollmentPanel = document.getElementById("enrollmentPanel");
const recognitionInfo = document.getElementById("recognitionInfo");
const facesInfo = document.getElementById("facesInfo");
const attendanceBody = document.getElementById("attendanceBody");
const confirmBtn = document.getElementById("confirmEnrollment");
const overlayMessage = document.getElementById("overlayMessage");
const enrollStatus = document.getElementById("enrollStatus");

const poses = [
    "Look straight",
    "Turn left",
    "Turn right",
    "Smile",
    "Move slightly back"
];

// Start camera only when dashboard loads
window.addEventListener("load", () => {
    document.getElementById("videoStream").src = "/video_feed";
});

// document.addEventListener("DOMContentLoaded", () => {
//     updateModeUI("recognition");
// });

fetch("/system/mode/recognition", { method: "POST" });

async function setMode(mode, opts = {}) {
    const { stopEnrollment = true } = opts;

    const video = document.getElementById("videoStream");
    if (video) video.src = "";

    hideOverlay();
    if (stopEnrollment) {
        enrollmentActive = false;
    }

    updateModeUI(mode);
    await fetch(`/system/mode/${mode}`, { method: "POST" });

    if (video) video.src = "/video_feed";
}

function exitSystem() {
    fetch("/camera/stop", { method: "POST" })
        .finally(() => {
            document.getElementById("videoStream").src = "";
            window.location.href = "/";
        });
}

function updateModeUI(mode) {
    const enrollPanel = document.getElementById("enrollment-panel");

    if (mode === "recognition") {
        enrollPanel.style.display = "none";
    } else if (mode === "enrollment") {
        enrollPanel.style.display = "block";
    }
}

// Collapsible sidebar (use existing HTML button)
const sidebar = document.getElementById("sidebar");
const toggleBtn = document.getElementById("toggleSidebar");

if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.classList.remove("active");
}

/* Sidebar toggle */
toggleBtn.onclick = () => {
    sidebar.classList.toggle("collapsed");
    toggleBtn.textContent = sidebar.classList.contains("collapsed") ? "❯❯" : "❮❮";
};




// System mode change
systemMode.addEventListener("change", async () => {
    await setMode(systemMode.value, { stopEnrollment: true });
});

/* Overlay helper */
function showOverlay(msg, color="#00ff99") {
    if (!overlayMessage) return;
    overlayMessage.innerText = msg;
    overlayMessage.style.color = color;
    overlayMessage.style.fontSize = "40px";
    overlayMessage.style.fontWeight = "600";
    // Keep the message away from pose debug text.
    overlayMessage.style.top = "auto";
    overlayMessage.style.bottom = "20px";
    overlayMessage.style.display = "block";
}

function hideOverlay() {
    if (!overlayMessage) return;
    overlayMessage.style.display = "none";
}

function setEnrollStatus(msg, color="#00ff99") {
    if (enrollStatus) {
        enrollStatus.innerText = msg;
    }
    showOverlay(msg, color);
}

function setConfirmState(isDone) {
    if (!confirmBtn) return;
    confirmBtn.disabled = !isDone;
    confirmBtn.classList.toggle("active", isDone);
}

// Fetch live recognition info every second
async function fetchRecognition() {
    try {
        const res = await fetch("/recognition/live");
        const data = await res.json();

        if (data.faces && data.faces.length > 0) {
            facesInfo.innerHTML = data.faces.map(f =>
                `<strong>${f.display_name}</strong> | ${f.role} | ${f.access_status} | d=${f.distance !== null ? f.distance.toFixed(2) : "--"}`
            ).join("<br>");
        } else {
            facesInfo.innerHTML = "No faces recognized";
        }

        if (data.attendance && data.attendance.length > 0) {
            attendanceBody.innerHTML = data.attendance.map(a =>
                `<tr>
                    <td>${a.timestamp}</td>
                    <td>${a.person_id}</td>
                    <td>${a.status}</td>
                    <td>${a.source}</td>
                </tr>`
            ).join("");
        }
    } catch (err) {
        console.error(err);
    }
    setTimeout(fetchRecognition, 1000);
}

fetchRecognition();

let enrollmentActive = false;

async function captureLoop() {
    if (!enrollmentActive) return;

    try {
        const res = await fetch("/enroll/capture", { method: "POST" });
        const data = await res.json();

        if (data.status === "calibrating") {
            // Calibration is expected at the beginning.
            const count = data.calib_count !== undefined ? data.calib_count : "";
            const suffix = count !== "" ? ` (${count})` : "";
            const hint = data.hint ? ` - ${data.hint}` : "";
            setEnrollStatus((data.message || "Calibrating...") + hint + suffix, "#00ff99");
            setConfirmState(false);
            setTimeout(captureLoop, 250);
            return;
        }

        if (data.status === "duplicate") {
            setEnrollStatus("Person already exists. Restarting enrollment", "#ff4444");
            setConfirmState(false);
            setTimeout(captureLoop, 800);
            return;
        }

        if (data.status === "ok") {
            const total = data.samples_required || poses.length;
            const poseLabel = poses[Math.min(data.count - 1, poses.length - 1)] || "Capture";
            const notice = data.notice ? ` | ${data.notice}` : "";
            setEnrollStatus(`${poseLabel} (${data.count}/${total}) | Quality ${data.quality}${notice}`);
            setConfirmState(data.done);

            if (!data.done) {
                setTimeout(captureLoop, 250);
            } else {
                setEnrollStatus("Capture complete. Click Confirm");
            }
        } else {
            setEnrollStatus(data.message || "Error during capture", "#ff4444");
            setTimeout(captureLoop, 350);
        }
    } catch (err) {
        console.error(err);
        setTimeout(captureLoop, 800);
    }
}

// Enrollment buttons
document.getElementById("startEnrollment").addEventListener("click", async () => {
    // Switch mode without racing the change handler.
    systemMode.value = "enrollment";
    await setMode("enrollment", { stopEnrollment: true });

    await fetch("/enroll/start", { method: "POST" });

    enrollmentActive = true;
    setEnrollStatus("Enrollment started. Look at camera.");

    captureLoop();
});

document.getElementById("confirmEnrollment").addEventListener("click", async () => {
    enrollmentActive = false;

    const payload = {
        display_name: document.getElementById("displayName").value,
        role: document.getElementById("role").value,
        department: document.getElementById("department").value,
        access_status: document.getElementById("accessStatus").value
    };

    const res = await fetch("/enroll/confirm", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
    });

    const data = await res.json();
    setEnrollStatus("Enrollment successful.");

    systemMode.value = "recognition";
    await setMode("recognition", { stopEnrollment: true });
});

// Force correct UI on page load
updateModeUI(systemMode.value);

document.getElementById("exitSystemBtn").addEventListener("click", () => {
    exitSystem();
});

/* End of script.js */
