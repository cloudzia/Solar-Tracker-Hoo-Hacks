# SMA-Based Solar Panel Tracking System

A low-cost, low-maintenance alternative to traditional motorized solar tracking using shape memory alloys (SMAs).

---

## Inspiration

*The Martian* describes a scenario where solar panels are fixed in place to avoid the added cost and complexity of motorized tracking systems. While this simplifies the design, fixed panels are significantly less efficient because solar output depends on the angle of incoming sunlight.

Even moderate misalignment can lead to substantial losses:

- 45° misalignment can reduce power by about 30%  
- 60° misalignment can reduce power by over 50%  

These losses are most noticeable in the morning and evening, when tracking systems provide the greatest benefit.

---

## Project Goal

The goal of this project is to create a more cost-effective and lower-maintenance solar tracking system by eliminating traditional motors.

By reducing mechanical complexity and minimizing moving parts, this design aims to provide a simpler and more reliable alternative. This approach is relevant both for Earth-based solar installations and for future space applications, where weight and maintenance are critical constraints.

---

## System Overview

### Actuation using Shape Memory Alloys

Shape memory alloys are materials that return to a predefined shape when heated due to reversible changes in their internal structure.

In this system:
- SMA wire is coiled within a 3D-printed structure  
- Electrical current heats the wire, causing it to contract  
- This contraction generates a force that tilts the solar panel  
- A spring provides the restoring force when the current is removed  

---

### Angle Measurement

- A potentiometer is connected to the rotation shaft  
- It provides continuous feedback on the panel’s tilt angle  

---

### Control System

- A Python-based PID controller is used for precise positioning  
- The controller regulates a constant-current power supply  
- It adjusts the current through the SMA wire to control its temperature and movement  

---

### Solar Position Tracking

- Wolfram Alpha is used to determine the position of the sun  
- The system calculates the optimal tilt angle based on time and location  

This approach can also be extended to other planetary environments, including Mars.

---

## Advantages

- Reduced cost compared to motor-driven tracking systems  
- Fewer moving parts, resulting in lower maintenance  
- Lightweight design  
- Potential for use in space applications  
- Improved efficiency compared to fixed panels  

---

## Future Work

- Improve the efficiency of SMA actuation  
- Add onboard solar position calculations to remove external dependencies  
- Improve response time and control accuracy  
- Expand the system to support multi-axis tracking  

---

## Summary

This project demonstrates that shape memory alloys can be used as an alternative to traditional motors in solar tracking systems, offering a simpler and potentially more robust solution for both terrestrial and space-based applications.
