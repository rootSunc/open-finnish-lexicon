"use strict";

const form = document.querySelector("#lookup");
const input = document.querySelector("#word");
const results = document.querySelector("#results");

function appendText(parent, tag, content, attributes = {}) {
  const element = document.createElement(tag);
  element.textContent = content;
  for (const [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, value);
  }
  parent.append(element);
}

function showLookup() {
  results.replaceChildren();
  const query = input.value.trim().normalize("NFC").toLocaleLowerCase("fi");
  if (!query) {
    appendText(results, "p", "Enter a Finnish word or inflected form.");
    return;
  }
  if (typeof sampleLookup === "undefined") {
    appendText(results, "p", "The sample could not load. Try reloading the page.");
    return;
  }
  if (!Object.hasOwn(sampleLookup, query)) {
    appendText(results, "p", "This word is outside the demo sample. Try one of the examples above.");
    return;
  }

  for (const entry of sampleLookup[query]) {
    const result = document.createElement("article");
    result.className = "result";
    appendText(result, "h2", entry.lemma, { lang: "fi" });
    appendText(result, "p", entry.part_of_speech === "num" ? "numeral" : entry.part_of_speech, {
      class: "part-of-speech",
    });
    appendText(result, "p", entry.gloss);
    const { person, number, tense, mood, case: grammaticalCase } = entry.features;
    const personLabel = { "1": "first person", "2": "second person", "3": "third person" }[person];
    const grammar = [personLabel, number, tense, mood, grammaticalCase].filter(Boolean).join(" · ");
    if (grammar) appendText(result, "p", grammar, { class: "grammar" });
    results.append(result);
  }
}

form.addEventListener("submit", event => {
  event.preventDefault();
  showLookup();
});

for (const button of document.querySelectorAll(".suggestions button")) {
  button.addEventListener("click", () => {
    input.value = button.textContent;
    showLookup();
  });
}

showLookup();
