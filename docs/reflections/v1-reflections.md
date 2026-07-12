# Version 1?

After having this sit on my shelf for a week, my thoughts in narrative form.

*It works. and it's better than using my phone*

The [time to leave](../insights.md#1-time-to-leave-not-departure-time) paradigm is just right. The ambient, "at a glance" thesis is correct: ambient availability is superior to a summons via smartphone. I dig for my phone less, and the out-the-door routine is less frantic. When eki-bin is off, I miss it. This is the most important finding of phase 1. 

*I knew the LED UX would matter, but still underestimated*

The lights are more annoying than I thought. The novelty of a cool breathing animation soon wears off. Then it just becomes an annoying blinking thing that won't shutup. More interesting is the slight variation in light refraction of a static led inside the curvature of a glass jar as you move around the room (see [jar physics & colour UX field notes](../insights.md#3-jar-physics--colour-ux--field-notes-2026-06-28)). The imperfections and wear of the glass make a nice differentiator. This goes back to one of the project's principles: it's hardware. A physical thing first and foremost. 

*The cost from "working breadboard" to "someone else can use this" is very high*

Right now it's a Pico 2W or ESP32C3 on breadboard with the 8-LED light stick shoved into a bottle. On a shelf high in the room, you actually don't see the breadboard as it's flat. But it's not usable beyond me: all settings changes require reflashing the firmware. There's no runtime input. It's a science project, really. To make this useful to someone else:
- **The whole unit has to fit into the bottle** This is actually harder than it sounds. Apparently wine bottles openings are about 20mm in diameter; sake bottles about the same. This means that, barring any industrial glass cutting, all hardware must be either skinnier than 20mm or flexible. Most hobby boards are wider than this. Cables add thickness. Nobody wants a breadboard on their shelf.
- **We have to enable settings control and setup without a smartphone app** How does the user input network information (for WiFi versions), change light patterns, enter station information etc. without reflashing each time? A Bluetooth- or WiFi-connected app is easy. But then we've reintroduced the problem we're trying to solve: smartphone dependency. 
- **It has to work, look good, and be better than the next-best alternative** Time sync must happen on startup (without a dedicated timekeeper module). It must manage to hide the internals enough so the "bottle" story is believable, even to a user who knows it's a smart bottle. And it has to work enough to earn trust on the user's shelf and supplant the engrained smartphone habit.
