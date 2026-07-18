"""A small, original corpus of short factual snippets for the demo RAG app.

Written from scratch for this project, not sourced from any copyrighted
text, so there's no provenance question for a public demo.
"""

from __future__ import annotations

CORPUS: list[dict[str, str]] = [
    {"id": "doc-1", "text": "The sun is a star at the center of the solar system."},
    {"id": "doc-2", "text": "Water boils at 100 degrees Celsius at sea level pressure."},
    {"id": "doc-3", "text": "Python is a popular programming language used in data science."},
    {"id": "doc-4", "text": "Mount Everest is the tallest mountain above sea level on Earth."},
    {"id": "doc-5", "text": "The Pacific Ocean is the largest and deepest ocean on Earth."},
    {"id": "doc-6", "text": "Photosynthesis lets plants convert sunlight into chemical energy."},
    {"id": "doc-7", "text": "The human heart has four chambers: two atria and two ventricles."},
    {
        "id": "doc-8",
        "text": "Light travels at approximately 300,000 kilometers per second in a vacuum.",
    },
    {"id": "doc-9", "text": "The Great Wall of China stretches for thousands of kilometers."},
    {
        "id": "doc-10",
        "text": "DNA carries the genetic instructions used in the growth of living things.",
    },
    {
        "id": "doc-11",
        "text": "Jupiter is the largest planet in the solar system by mass and volume.",
    },
    {"id": "doc-12", "text": "The French Revolution began in 1789 and reshaped European politics."},
    {"id": "doc-13", "text": "A byte is typically made up of eight bits in modern computing."},
    {
        "id": "doc-14",
        "text": "The Amazon rainforest produces a significant share of the world's oxygen.",
    },
    {"id": "doc-15", "text": "Sharks have existed on Earth for hundreds of millions of years."},
    {"id": "doc-16", "text": "The Sahara is the largest hot desert in the world by area."},
    {"id": "doc-17", "text": "Honey never spoils if it is stored properly in a sealed container."},
    {"id": "doc-18", "text": "The speed of sound in dry air is about 343 meters per second."},
    {"id": "doc-19", "text": "Octopuses have three hearts and blue, copper-based blood."},
    {
        "id": "doc-20",
        "text": "The Great Barrier Reef is the largest coral reef system in the world.",
    },
    {
        "id": "doc-21",
        "text": "Ancient Rome's empire spanned three continents at its greatest extent.",
    },
    {
        "id": "doc-22",
        "text": "A leap year adds one extra day to the calendar to keep it aligned with Earth's orbit.",
    },
    {
        "id": "doc-23",
        "text": "Gold is a dense, soft metal that does not corrode or tarnish easily.",
    },
    {"id": "doc-24", "text": "The human body contains roughly 206 bones once fully grown."},
    {"id": "doc-25", "text": "Antarctica is the coldest, driest, and windiest continent on Earth."},
    {
        "id": "doc-26",
        "text": "The printing press, developed in the 15th century, transformed the spread of information.",
    },
    {
        "id": "doc-27",
        "text": "Bees communicate the location of food sources through a waggle dance.",
    },
    {"id": "doc-28", "text": "The Nile is often cited as one of the longest rivers in the world."},
    {
        "id": "doc-29",
        "text": "A computer's CPU executes instructions that make up running programs.",
    },
    {
        "id": "doc-30",
        "text": "Venus is the hottest planet in the solar system due to its thick atmosphere.",
    },
    {"id": "doc-31", "text": "Volcanic eruptions can release ash that affects climate for months."},
    {"id": "doc-32", "text": "The human brain contains roughly 86 billion neurons."},
    {"id": "doc-33", "text": "Coral reefs support an enormous diversity of marine life."},
    {
        "id": "doc-34",
        "text": "The Wright brothers achieved the first powered airplane flight in 1903.",
    },
    {
        "id": "doc-35",
        "text": "Diamonds form under extreme heat and pressure deep within the Earth.",
    },
    {
        "id": "doc-36",
        "text": "The Great Depression of the 1930s caused widespread global economic hardship.",
    },
    {"id": "doc-37", "text": "Penguins are flightless birds that are highly adapted to swimming."},
    {
        "id": "doc-38",
        "text": "A network protocol defines rules for how data is exchanged between computers.",
    },
    {
        "id": "doc-39",
        "text": "The Eiffel Tower was completed in 1889 for the World's Fair in Paris.",
    },
    {"id": "doc-40", "text": "Migratory birds can travel thousands of kilometers between seasons."},
    {"id": "doc-41", "text": "Earth's atmosphere is composed mostly of nitrogen and oxygen."},
    {
        "id": "doc-42",
        "text": "The invention of the wheel greatly improved transportation in ancient times.",
    },
    {
        "id": "doc-43",
        "text": "Machine learning models improve their performance by learning from data.",
    },
    {"id": "doc-44", "text": "The Mariana Trench is the deepest known part of the world's oceans."},
    {
        "id": "doc-45",
        "text": "Vaccines train the immune system to recognize and fight specific pathogens.",
    },
    {
        "id": "doc-46",
        "text": "The Renaissance was a period of renewed interest in art and science in Europe.",
    },
    {"id": "doc-47", "text": "Glaciers store a large portion of the world's fresh water as ice."},
    {
        "id": "doc-48",
        "text": "A firewall filters network traffic based on configured security rules.",
    },
    {"id": "doc-49", "text": "Bats are the only mammals capable of sustained, powered flight."},
    {
        "id": "doc-50",
        "text": "The stock market allows investors to buy and sell shares of companies.",
    },
]
