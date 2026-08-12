// ---------------------------------------------------------------------
// GENDER AUTO-DETECTION (student_form.html)
// ---------------------------------------------------------------------
function initGenderDetect() {
    const nameInput = document.getElementById("full_name");
    const genderSelect = document.getElementById("gender");
    const confirmCheckbox = document.getElementById("gender_confirmed");
    const hint = document.getElementById("gender-hint");
    if (!nameInput || !genderSelect) return;

    let debounceTimer;
    nameInput.addEventListener("input", function () {
        clearTimeout(debounceTimer);
        // Any manual name edit means previous confirmation no longer applies
        if (confirmCheckbox) confirmCheckbox.checked = false;
        debounceTimer = setTimeout(async () => {
            const name = nameInput.value.trim();
            if (!name) {
                if (hint) hint.textContent = "";
                return;
            }
            try {
                const res = await fetch(`/api/detect-gender?name=${encodeURIComponent(name)}`);
                const data = await res.json();
                if (data.gender) {
                    genderSelect.value = data.gender;
                    if (hint) {
                        hint.textContent = `Detected gender: ${data.gender} (please confirm or change if incorrect)`;
                        hint.className = "form-text text-success";
                    }
                } else {
                    if (hint) {
                        hint.textContent = "Could not automatically detect gender from this name. Please select and confirm it manually.";
                        hint.className = "form-text text-warning";
                    }
                }
            } catch (e) {
                console.error("Gender detect failed", e);
            }
        }, 450);
    });

    // Manually changing the dropdown counts as a confirmation
    genderSelect.addEventListener("change", function () {
        if (confirmCheckbox) confirmCheckbox.checked = true;
    });
}

// ---------------------------------------------------------------------
// LIVE TOTAL / AVERAGE / GRADE PREVIEW (marks.html)
// ---------------------------------------------------------------------
const GRADE_BANDS = [
    { letter: "A", low: 81, high: 100, cls: "grade-A" },
    { letter: "B", low: 61, high: 80, cls: "grade-B" },
    { letter: "C", low: 41, high: 60, cls: "grade-C" },
    { letter: "D", low: 21, high: 40, cls: "grade-D" },
    { letter: "E", low: 0, high: 20, cls: "grade-E" },
];

function gradeFor(avg) {
    for (const b of GRADE_BANDS) {
        if (avg >= b.low && avg <= b.high) return b;
    }
    return { letter: "-", cls: "grade--" };
}

function recalcRow(studentId) {
    const inputs = document.querySelectorAll(`.score-input[data-student="${studentId}"]`);
    let total = 0, count = 0;
    inputs.forEach((inp) => {
        const v = parseFloat(inp.value);
        if (!isNaN(v)) { total += v; count += 1; }
    });
    const avg = count ? total / count : null;
    const totalCell = document.getElementById(`total-${studentId}`);
    const avgCell = document.getElementById(`avg-${studentId}`);
    const gradeCell = document.getElementById(`grade-${studentId}`);
    if (totalCell) totalCell.textContent = count ? total.toFixed(0) : "-";
    if (avgCell) avgCell.textContent = avg !== null ? avg.toFixed(1) : "-";
    if (gradeCell) {
        const g = avg !== null ? gradeFor(avg) : { letter: "-", cls: "grade--" };
        gradeCell.innerHTML = `<span class="grade-badge ${g.cls}">${g.letter}</span>`;
    }
}

function initMarksEntry() {
    const inputs = document.querySelectorAll(".score-input");
    if (!inputs.length) return;
    inputs.forEach((inp) => {
        inp.addEventListener("input", () => recalcRow(inp.dataset.student));
        recalcRow(inp.dataset.student);
    });
}

document.addEventListener("DOMContentLoaded", function () {
    initGenderDetect();
    initMarksEntry();

    // sidebar toggle for small screens
    const toggleBtn = document.getElementById("sidebarToggle");
    if (toggleBtn) {
        toggleBtn.addEventListener("click", () => {
            document.querySelector(".sidebar").classList.toggle("d-none");
        });
    }

    // auto-dismiss flash alerts
    document.querySelectorAll(".alert-auto-dismiss").forEach((el) => {
        setTimeout(() => { el.classList.remove("show"); }, 4000);
    });
});

function printReport() {
    window.print();
}
