# Failure Taxonomy & Root-Cause Analysis

- **Evaluation Timestamp**: `2026-11-01T11:14:02.158924+00:00`
- **Dataset Evaluated**: `100` questions
- **Total Identified Failures**: `61`

## Breakdown of Observed Failures

### 1. [N01] Category: `generation_error`
- **Question**: What is the minimum number of credits required to earn the B.Tech degree?
- **Role**: `student`
- **Expected**: 160 credits.
- **Got**: According to the documentation, Academic Regulations for Undergraduate Programmes [1]. According to the documentation, 2...
- **Root Cause**: Synthesized answer missing required key facts: ['160 credits.']

### 2. [N02] Category: `generation_error`
- **Question**: How many credits can I register for in a semester?
- **Role**: `student`
- **Expected**: Minimum 16 and maximum 24 credits; the normal load is 20 credits.
- **Got**: According to the documentation, Academic Regulations for Undergraduate Programmes [1]. According to the documentation, 2...
- **Root Cause**: Synthesized answer missing required key facts: ['Minimum 16 and maximum 24 credits; the normal load is 20 credits.']

### 3. [N03] Category: `generation_error`
- **Question**: How many grade points does an A+ grade carry?
- **Role**: `student`
- **Expected**: 9 grade points (80 to 89 marks).
- **Got**: According to the documentation, 2. Grading and CGPA [1]. According to the documentation, 3. Progression, withdrawal and ...
- **Root Cause**: Synthesized answer missing required key facts: ['9 grade points (80 to 89 marks).']

### 4. [N04] Category: `generation_error`
- **Question**: What is the minimum CGPA required for the award of the degree?
- **Role**: `student`
- **Expected**: A minimum CGPA of 5.0.
- **Got**: According to the documentation, 2. Renewal, documents and decisions [1]. According to the documentation, Scholarship Gui...
- **Root Cause**: Synthesized answer missing required key facts: ['A minimum CGPA of 5.0.']

### 5. [N05] Category: `generation_error`
- **Question**: How many backlog courses can I carry into the next academic year?
- **Role**: `student`
- **Expected**: A maximum of 6 active backlog courses; more than that blocks promotion.
- **Got**: According to the documentation, 3. Progression, withdrawal and duration [1]. According to the documentation, Academic Re...
- **Root Cause**: Synthesized answer missing required key facts: ['A maximum of 6 active backlog courses; more than that blocks promotion.']

### 6. [N06] Category: `generation_error`
- **Question**: Until when can I withdraw from a course without a grade penalty?
- **Role**: `student`
- **Expected**: Within 14 days of the start of the semester.
- **Got**: According to the documentation, 3. Progression, withdrawal and duration [1]. According to the documentation, 2. Fines, r...
- **Root Cause**: Synthesized answer missing required key facts: ['Within 14 days of the start of the semester.']

### 7. [N07] Category: `generation_error`
- **Question**: What is the maximum time allowed to complete the B.Tech programme?
- **Role**: `student`
- **Expected**: 6 academic years from the date of admission.
- **Got**: According to the documentation, Academic Regulations for Undergraduate Programmes [1]. According to the documentation, 3...
- **Root Cause**: Synthesized answer missing required key facts: ['6 academic years from the date of admission.']

### 8. [N08] Category: `generation_error`
- **Question**: What happens if my CGPA is below 5.0 at the end of an academic year?
- **Role**: `student`
- **Expected**: The student is placed on academic probation for the following year.
- **Got**: According to the documentation, 3. Progression, withdrawal and duration [1]. According to the documentation, 2. Grading ...
- **Root Cause**: Synthesized answer missing required key facts: ['The student is placed on academic probation for the following year.']

### 9. [N09] Category: `generation_error`
- **Question**: How much is the replacement fee for a lost ID card?
- **Role**: `student`
- **Expected**: Rs. 300.
- **Got**: According to the documentation, Student Handbook [1]. According to the documentation, 2. Fines, renewals and conduct [2]...
- **Root Cause**: Synthesized answer missing required key facts: ['Rs. 300.']

### 10. [N10] Category: `generation_error`
- **Question**: What are the opening and closing times of the campus gates?
- **Role**: `student`
- **Expected**: 6:00 AM to 10:00 PM.
- **Got**: According to the documentation, Student Handbook [1]. According to the documentation, 3. Grievances and student life [2]...
- **Root Cause**: Synthesized answer missing required key facts: ['6:00 AM to 10:00 PM.']

### 11. [N11] Category: `generation_error`
- **Question**: Are mobile phones allowed inside examination halls?
- **Role**: `student`
- **Expected**: No, mobile phones are not permitted inside examination halls.
- **Got**: According to the documentation, 2. Code of conduct [1]. According to the documentation, Hostel Rules [2].
- **Root Cause**: Synthesized answer missing required key facts: ['No, mobile phones are not permitted inside examination halls.']

### 12. [N13] Category: `generation_error`
- **Question**: How quickly does the Student Grievance Cell acknowledge a complaint?
- **Role**: `student`
- **Expected**: Within 3 working days (resolution aimed within 15 working days).
- **Got**: According to the documentation, 3. Grievances and student life [1]. According to the documentation, - Clause 3.2. No stu...
- **Root Cause**: Synthesized answer missing required key facts: ['Within 3 working days (resolution aimed within 15 working days).']

### 13. [N14] Category: `generation_error`
- **Question**: What is needed to register a student club?
- **Role**: `student`
- **Expected**: At least 15 members and a faculty advisor.
- **Got**: According to the documentation, 3. Grievances and student life [1]. According to the documentation, Student Handbook [2]...
- **Root Cause**: Synthesized answer missing required key facts: ['At least 15 members and a faculty advisor.']

### 14. [N15] Category: `generation_error`
- **Question**: When is the Counselling Centre open and is it free?
- **Role**: `student`
- **Expected**: Monday to Saturday, 9:00 AM to 5:00 PM; free and confidential.
- **Got**: According to the documentation, 3. Grievances and student life [1]. According to the documentation, Student Handbook [2]...
- **Root Cause**: Synthesized answer missing required key facts: ['Monday to Saturday, 9:00 AM to 5:00 PM; free and confidential.']

### 15. [N16] Category: `generation_error`
- **Question**: How can I report ragging, and can I do it anonymously?
- **Role**: `student`
- **Expected**: Contact the Anti-Ragging Committee via helpline extension 1100; anonymous complaints are allowed.
- **Got**: According to the documentation, 2. Code of conduct [1]. According to the documentation, 3. Grievances and student life [...
- **Root Cause**: Synthesized answer missing required key facts: ['Contact the Anti-Ragging Committee via helpline extension 1100; anonymous complaints are allowed.']

### 16. [N17] Category: `generation_error`
- **Question**: How long do I have to appeal a grievance decision to the Dean of Student Affairs?
- **Role**: `student`
- **Expected**: Within 7 days of receiving the decision.
- **Got**: According to the documentation, 3. Grievances and student life [1]. According to the documentation, 2. Renewal, document...
- **Root Cause**: Synthesized answer missing required key facts: ['Within 7 days of receiving the decision.']

### 17. [N20] Category: `generation_error`
- **Question**: What aggregate mark do I need to pass a theory course?
- **Role**: `student`
- **Expected**: At least 40 out of 100 (CIA plus ESE).
- **Got**: According to the documentation, - Amendment to Clause 4.2: the minimum ESE mark required to pass a theory course is redu...
- **Root Cause**: Synthesized answer missing required key facts: ['At least 40 out of 100 (CIA plus ESE).']

### 18. [N22] Category: `generation_error`
- **Question**: What is the penalty for a first offence of using unfair means in an exam?
- **Role**: `student`
- **Expected**: The answer paper of that course is cancelled.
- **Got**: According to the documentation, 3. Unfair means and supplementary examinations [1]. According to the documentation, - Cl...
- **Root Cause**: Synthesized answer missing required key facts: ['The answer paper of that course is cancelled.']

### 19. [N25] Category: `abstain_error`
- **Question**: If my answer script is re-evaluated, can my marks go down?
- **Role**: `student`
- **Expected**: No. Re-evaluated marks replace the original marks only if they are higher.
- **Got**: I do not have sufficient information in the provided documents to answer this question.
- **Root Cause**: Falsely abstained on an answerable query.

### 20. [N26] Category: `generation_error`
- **Question**: How many books can an undergraduate borrow from the library and for how long?
- **Role**: `student`
- **Expected**: 4 books for 14 days.
- **Got**: According to the documentation, Library Rules [1]. According to the documentation, 2. Fines, renewals and conduct [2].
- **Root Cause**: Synthesized answer missing required key facts: ['4 books for 14 days.']

### 21. [N27] Category: `generation_error`
- **Question**: What are the library opening hours?
- **Role**: `student`
- **Expected**: 8:30 AM to 8:00 PM, Monday to Saturday; open until midnight during end-semester exams.
- **Got**: According to the documentation, Library Rules [1]. According to the documentation, Hostel Rules [2].
- **Root Cause**: Synthesized answer missing required key facts: ['8:30 AM to 8:00 PM, Monday to Saturday; open until midnight during end-semester exams.']

### 22. [N30] Category: `generation_error`
- **Question**: What must I do if I lose a library book?
- **Role**: `student`
- **Expected**: Replace it with the same edition or pay twice the price of the book.
- **Got**: According to the documentation, 2. Fines, renewals and conduct [1]. According to the documentation, Library Rules [2].
- **Root Cause**: Synthesized answer missing required key facts: ['Replace it with the same edition or pay twice the price of the book.']

### 23. [N31] Category: `abstain_error`
- **Question**: Can I take reference books home?
- **Role**: `student`
- **Expected**: No. Reference books, journals and past question papers must be used inside the library.
- **Got**: I do not have sufficient information in the provided documents to answer this question.
- **Root Cause**: Falsely abstained on an answerable query.

### 24. [N32] Category: `generation_error`
- **Question**: Which scholarship gives a 50% tuition waiver and who qualifies?
- **Role**: `student`
- **Expected**: The Merit Scholarship: top 5% of the programme by CGPA with a minimum CGPA of 8.5.
- **Got**: According to the documentation, Scholarship Guidelines [1]. According to the documentation, - Sports Scholarship: studen...
- **Root Cause**: Synthesized answer missing required key facts: ['The Merit Scholarship: top 5% of the programme by CGPA with a minimum CGPA of 8.5.']

### 25. [N33] Category: `generation_error`
- **Question**: What family income limit applies to the need-based scholarship, and how much is waived?
- **Role**: `student`
- **Expected**: Family annual income below Rs. 4,00,000; 30% of tuition fees waived.
- **Got**: According to the documentation, Scholarship Guidelines [1]. According to the documentation, 2. Renewal, documents and de...
- **Root Cause**: Synthesized answer missing required key facts: ['Family annual income below Rs. 4,00,000; 30% of tuition fees waived.']

### 26. [N34] Category: `generation_error`
- **Question**: What is the deadline to apply for scholarships?
- **Role**: `student`
- **Expected**: 31 August each year, on the scholarship portal.
- **Got**: According to the documentation, 2. Renewal, documents and decisions [1]. According to the documentation, - Sports Schola...
- **Root Cause**: Synthesized answer missing required key facts: ['31 August each year, on the scholarship portal.']

### 27. [N35] Category: `generation_error`
- **Question**: Can I hold two scholarships at the same time?
- **Role**: `student`
- **Expected**: No. Only one scholarship at a time; waivers cannot be combined.
- **Got**: According to the documentation, - Sports Scholarship: students who have represented their state or country at an officia...
- **Root Cause**: Synthesized answer missing required key facts: ['No. Only one scholarship at a time; waivers cannot be combined.']

### 28. [N36] Category: `generation_error`
- **Question**: Which documents do I need for a scholarship application?
- **Role**: `student`
- **Expected**: Income certificate (need-based), previous semester marksheet and a copy of the bank passbook.
- **Got**: According to the documentation, 2. Renewal, documents and decisions [1]. According to the documentation, - Sports Schola...
- **Root Cause**: Synthesized answer missing required key facts: ['Income certificate (need-based), previous semester marksheet and a copy of the bank passbook.']

### 29. [N37] Category: `generation_error`
- **Question**: What minimum CGPA do I need to renew my scholarship?
- **Role**: `student`
- **Expected**: A CGPA of at least 7.5 (plus meeting the minimum attendance requirement).
- **Got**: According to the documentation, 2. Renewal, documents and decisions [1]. According to the documentation, Scholarship Gui...
- **Root Cause**: Synthesized answer missing required key facts: ['A CGPA of at least 7.5 (plus meeting the minimum attendance requirement).']

### 30. [N38] Category: `generation_error`
- **Question**: What attendance percentage must I maintain to renew my scholarship under the current rules?
- **Role**: `student`
- **Expected**: At least 75%, the minimum attendance under the current (2025) Attendance and Leave Policy, together with a CGPA of at least 7.5.
- **Got**: Under the current policy, the minimum course attendance requirement is 75% [1]. However, this supersedes the previous po...
- **Root Cause**: Synthesized answer missing required key facts: ['At least 75%, the minimum attendance under the current (2025) Attendance and Leave Policy, together with a CGPA of at least 7.5.']

### 31. [N39] Category: `generation_error`
- **Question**: How long do I have to appeal a scholarship decision?
- **Role**: `student`
- **Expected**: Within 10 days of the announcement.
- **Got**: According to the documentation, 2. Renewal, documents and decisions [1]. According to the documentation, - Sports Schola...
- **Root Cause**: Synthesized answer missing required key facts: ['Within 10 days of the announcement.']

### 32. [N40] Category: `generation_error`
- **Question**: How much is the hostel security deposit and is it refundable?
- **Role**: `student`
- **Expected**: Rs. 10,000, refundable.
- **Got**: According to the documentation, 2. Fees, mess and discipline [1]. According to the documentation, Hostel Rules [2].
- **Root Cause**: Synthesized answer missing required key facts: ['Rs. 10,000, refundable.']

### 33. [N41] Category: `generation_error`
- **Question**: Can I use an electric kettle or induction stove in my hostel room?
- **Role**: `student`
- **Expected**: No. Cooking appliances such as induction stoves, heaters and electric kettles are not allowed in rooms.
- **Got**: According to the documentation, 2. Fees, mess and discipline [1]. According to the documentation, Hostel Rules [2].
- **Root Cause**: Synthesized answer missing required key facts: ['No. Cooking appliances such as induction stoves, heaters and electric kettles are not allowed in rooms.']

### 34. [N42] Category: `generation_error`
- **Question**: What is the fine for violating hostel rules?
- **Role**: `student`
- **Expected**: Up to Rs. 2,000, and it may lead to suspension from the hostel.
- **Got**: Under the current policy, the hostel curfew timing is 10:30 PM [1]. However, this supersedes the previous policy, which ...
- **Root Cause**: Synthesized answer missing required key facts: ['Up to Rs. 2,000, and it may lead to suspension from the hostel.']

### 35. [N43] Category: `generation_error`
- **Question**: Are overnight guests allowed in the hostel?
- **Role**: `student`
- **Expected**: No, overnight guests are not permitted.
- **Got**: Under the current policy, the hostel curfew timing is 10:30 PM [1]. However, this supersedes the previous policy, which ...
- **Root Cause**: Synthesized answer missing required key facts: ['No, overnight guests are not permitted.']

### 36. [N45] Category: `generation_error`
- **Question**: Can I get a mess rebate if I am away from the hostel?
- **Role**: `student`
- **Expected**: Yes, if absent for 3 or more consecutive days: a rebate of Rs. 80 per day.
- **Got**: According to the documentation, 2. Fees, mess and discipline [1]. According to the documentation, Hostel Rules [2].
- **Root Cause**: Synthesized answer missing required key facts: ['Yes, if absent for 3 or more consecutive days: a rebate of Rs. 80 per day.']

### 37. [N46] Category: `generation_error`
- **Question**: When does the student portal send me an attendance warning?
- **Role**: `student`
- **Expected**: An automatic warning email is sent when attendance in any course falls below 80%.
- **Got**: According to the documentation, 2. Leave procedure and monitoring [1]. According to the documentation, 2025. From that d...
- **Root Cause**: Synthesized answer missing required key facts: ['An automatic warning email is sent when attendance in any course falls below 80%.']

### 38. [N47] Category: `generation_error`
- **Question**: How much on-duty leave counts as present attendance?
- **Role**: `student`
- **Expected**: Approved on-duty classes count as present, capped at 10% of the classes conducted in the course.
- **Got**: According to the documentation, 2. Leave procedure and monitoring [1]. According to the documentation, Attendance and Le...
- **Root Cause**: Synthesized answer missing required key facts: ['Approved on-duty classes count as present, capped at 10% of the classes conducted in the course.']

### 39. [N48] Category: `generation_error`
- **Question**: What proof do I need for medical leave?
- **Role**: `student`
- **Expected**: A certificate from a registered medical practitioner.
- **Got**: According to the documentation, 2. Leave procedure and monitoring [1]. According to the documentation, 2. Leave procedur...
- **Root Cause**: Synthesized answer missing required key facts: ['A certificate from a registered medical practitioner.']

### 40. [N51] Category: `generation_error`
- **Question**: How many library books can faculty members borrow and for how long?
- **Role**: `faculty`
- **Expected**: 10 books at a time for 60 days.
- **Got**: According to the documentation, Library Rules [1]. According to the documentation, Faculty Service Rules [2].
- **Root Cause**: Synthesized answer missing required key facts: ['10 books at a time for 60 days.']

### 41. [N52] Category: `generation_error`
- **Question**: Who can condone a student's attendance shortage?
- **Role**: `faculty`
- **Expected**: The Dean of Academics.
- **Got**: Under the current policy, the minimum course attendance requirement is 75% [1]. However, this supersedes the previous po...
- **Root Cause**: Synthesized answer missing required key facts: ['The Dean of Academics.']

### 42. [N54] Category: `generation_error`
- **Question**: How many grade points does a D grade carry, and is F a pass?
- **Role**: `student`
- **Expected**: D (40 to 49 marks) carries 5 grade points. F (below 40) carries 0 grade points and is a fail.
- **Got**: According to the documentation, 2. Grading and CGPA [1]. According to the documentation, 3. Progression, withdrawal and ...
- **Root Cause**: Synthesized answer missing required key facts: ['D (40 to 49 marks) carries 5 grade points. F (below 40) carries 0 grade points and is a fail.']

### 43. [N55] Category: `generation_error`
- **Question**: How many books can a postgraduate student borrow and for how many days?
- **Role**: `student`
- **Expected**: 6 books for 21 days.
- **Got**: According to the documentation, Library Rules [1]. According to the documentation, Academic Regulations for Undergraduat...
- **Root Cause**: Synthesized answer missing required key facts: ['6 books for 21 days.']

### 44. [S01] Category: `generation_error`
- **Question**: What is the minimum attendance I need in each course to write the end-semester exam?
- **Role**: `student`
- **Expected**: 75% (2025 policy, effective 1 July 2025).
- **Got**: Under the current policy, the minimum course attendance requirement is 75% [1]. However, this supersedes the previous po...
- **Root Cause**: Synthesized answer missing required key facts: ['75% (2025 policy, effective 1 July 2025).']

### 45. [S03] Category: `generation_error`
- **Question**: What is the lowest attendance percentage that can still be condoned?
- **Role**: `student`
- **Expected**: 65%. Below 65% cannot be condoned.
- **Got**: Under the current policy, the minimum course attendance requirement is 75% [1]. However, this supersedes the previous po...
- **Root Cause**: Synthesized answer missing required key facts: ['65%. Below 65% cannot be condoned.']

### 46. [S04] Category: `generation_error`
- **Question**: How many days after returning to class can I submit my leave application?
- **Role**: `student`
- **Expected**: Within 5 days, through the student portal.
- **Got**: According to the documentation, 2. Leave procedure and monitoring [1]. According to the documentation, 2. Leave procedur...
- **Root Cause**: Synthesized answer missing required key facts: ['Within 5 days, through the student portal.']

### 47. [S05] Category: `generation_error`
- **Question**: What is the minimum ESE score needed to pass a theory course?
- **Role**: `student`
- **Expected**: 21 out of 60 (35%), as amended by Circular KVIT/ACAD/2025/014 effective 1 July 2025.
- **Got**: According to the documentation, - Amendment to Clause 4.2: the minimum ESE mark required to pass a theory course is redu...
- **Root Cause**: Synthesized answer missing required key facts: ['21 out of 60 (35%), as amended by Circular KVIT/ACAD/2025/014 effective 1 July 2025.']

### 48. [S06] Category: `generation_error`
- **Question**: What is the re-evaluation fee per paper?
- **Role**: `student`
- **Expected**: Rs. 600 per paper (amended; effective 1 July 2025).
- **Got**: According to the documentation, - Amendment to Clause 6.1: the re-evaluation application window is extended from 5 worki...
- **Root Cause**: Synthesized answer missing required key facts: ['Rs. 600 per paper (amended; effective 1 July 2025).']

### 49. [S07] Category: `generation_error`
- **Question**: How many working days do I have to apply for re-evaluation after results are published?
- **Role**: `student`
- **Expected**: 7 working days (amended; effective 1 July 2025).
- **Got**: According to the documentation, - Amendment to Clause 6.1: the re-evaluation application window is extended from 5 worki...
- **Root Cause**: Synthesized answer missing required key facts: ['7 working days (amended; effective 1 July 2025).']

### 50. [S08] Category: `generation_error`
- **Question**: What is the hostel curfew time?
- **Role**: `student`
- **Expected**: 10:30 PM (2025 rules).
- **Got**: Under the current policy, the hostel curfew timing is 10:30 PM [1]. However, this supersedes the previous policy, which ...
- **Root Cause**: Synthesized answer missing required key facts: ['10:30 PM (2025 rules).']

### 51. [S09] Category: `generation_error`
- **Question**: Until what time are visitors allowed in the hostel visitors' room?
- **Role**: `student`
- **Expected**: Until 7:00 PM (2025 rules).
- **Got**: Under the current policy, the hostel curfew timing is 10:30 PM [1]. However, this supersedes the previous policy, which ...
- **Root Cause**: Synthesized answer missing required key facts: ['Until 7:00 PM (2025 rules).']

### 52. [S10] Category: `generation_error`
- **Question**: Can I enter the hostel after curfew if I am running late?
- **Role**: `student`
- **Expected**: Yes. Each resident gets up to 4 late passes per month, approved by the warden on the hostel app, allowing entry up to 11:30 PM.
- **Got**: Under the current policy, the hostel curfew timing is 10:30 PM [1]. However, this supersedes the previous policy, which ...
- **Root Cause**: Synthesized answer missing required key facts: ['Yes. Each resident gets up to 4 late passes per month, approved by the warden on the hostel app, allowing entry up to 11:30 PM.']

### 53. [S11] Category: `generation_error`
- **Question**: Which attendance and leave policy is currently in force?
- **Role**: `student`
- **Expected**: The 2025 Attendance and Leave Policy, effective 1 July 2025, which replaced the policy dated 1 August 2023.
- **Got**: Under the current policy, the minimum course attendance requirement is 75% [1]. However, this supersedes the previous po...
- **Root Cause**: Synthesized answer missing required key facts: ['The 2025 Attendance and Leave Policy, effective 1 July 2025, which replaced the policy dated 1 August 2023.']

### 54. [S12] Category: `generation_error`
- **Question**: My senior says 80% attendance is mandatory. Is that still true?
- **Role**: `student`
- **Expected**: No. Since 1 July 2025 the minimum is 75% per course; the 80% rule was in the superseded 2023 policy.
- **Got**: Under the current policy, the minimum course attendance requirement is 75% [1]. However, this supersedes the previous po...
- **Root Cause**: Synthesized answer missing required key facts: ['No. Since 1 July 2025 the minimum is 75% per course; the 80% rule was in the superseded 2023 policy.']

### 55. [S13] Category: `generation_error`
- **Question**: From which date do the amended pass-mark and re-evaluation rules apply?
- **Role**: `student`
- **Expected**: From 1 July 2025 (Circular KVIT/ACAD/2025/014, approved by the Academic Council on 28 May 2025).
- **Got**: According to the documentation, - Amendment to Clause 6.1: the re-evaluation application window is extended from 5 worki...
- **Root Cause**: Synthesized answer missing required key facts: ['From 1 July 2025 (Circular KVIT/ACAD/2025/014, approved by the Academic Council on 28 May 2025).']

### 56. [S14] Category: `generation_error`
- **Question**: Did the 2025 circular change the aggregate pass mark of 40 out of 100 for theory courses?
- **Role**: `student`
- **Expected**: No. The aggregate requirement of 40 out of 100 is unchanged; only the minimum ESE mark was reduced.
- **Got**: According to the documentation, - Amendment to Clause 4.2: the minimum ESE mark required to pass a theory course is redu...
- **Root Cause**: Synthesized answer missing required key facts: ['No. The aggregate requirement of 40 out of 100 is unchanged; only the minimum ESE mark was reduced.']

### 57. [R11] Category: `generation_error`
- **Question**: How many days of casual leave am I entitled to per year?
- **Role**: `faculty`
- **Expected**: 12 days per calendar year, with no more than 4 consecutive days at a time.
- **Got**: According to the documentation, Faculty Service Rules [1]. According to the documentation, - Earned leave: 30 days per c...
- **Root Cause**: Synthesized answer missing required key facts: ['12 days per calendar year, with no more than 4 consecutive days at a time.']

### 58. [R12] Category: `generation_error`
- **Question**: When can marks moderation be applied and how many marks can it add?
- **Role**: `faculty`
- **Expected**: When the class average ESE score is below 45%; it may add up to 5 marks for the whole class, subject to Moderation Committee approval.
- **Got**: According to the documentation, Marks Moderation Guidelines [1]. According to the documentation, 2. Confidentiality [2].
- **Root Cause**: Synthesized answer missing required key facts: ['When the class average ESE score is below 45%; it may add up to 5 marks for the whole class, subject to Moderation Committee approval.']

### 59. [R13] Category: `generation_error`
- **Question**: How many days before the end-semester exam must I submit my question papers?
- **Role**: `faculty`
- **Expected**: At least 21 days before the start of the end-semester examinations.
- **Got**: According to the documentation, Question Paper Confidentiality Protocol [1]. According to the documentation, Library Rul...
- **Root Cause**: Synthesized answer missing required key facts: ['At least 21 days before the start of the end-semester examinations.']

### 60. [R14] Category: `generation_error`
- **Question**: How many disciplinary cases were heard between January and June 2025, and of what kinds?
- **Role**: `admin`
- **Expected**: 9 cases: 4 plagiarism, 3 examination malpractice and 2 hostel violations.
- **Got**: Under the historical policy in effect at that time (historical rule, no longer in force today), 1. Summary of cases, Jan...
- **Root Cause**: Synthesized answer missing required key facts: ['9 cases: 4 plagiarism, 3 examination malpractice and 2 hostel violations.']

### 61. [R15] Category: `generation_error`
- **Question**: What is the size of the discretionary fee waiver pool and the Principal's approval limit?
- **Role**: `admin`
- **Expected**: Rs. 25,00,000 for 2025-26; the Principal can approve up to Rs. 50,000 per student without a committee.
- **Got**: According to the documentation, Discretionary Fee Waiver: Internal Criteria [1]. According to the documentation, Scholar...
- **Root Cause**: Synthesized answer missing required key facts: ['Rs. 25,00,000 for 2025-26; the Principal can approve up to Rs. 50,000 per student without a committee.']

## Failure Taxonomy Reference

| Category | Definition | Recovery Mechanism |
| :--- | :--- | :--- |
| `retrieval_miss` | Target chunk absent from initial top-K hybrid candidates | Expand BM25 synonyms / increase top-K candidate pool |
| `rerank_drop` | Target chunk retrieved by hybrid search but dropped by cross-encoder | Tune cross-encoder threshold or weight RRF fusion rank |
| `lineage_miss` | Stale or superseded chunk cited instead of active version | Verify DAG topological sort in DocumentVersionService |
| `generation_error` | Missing key factual assertion or ungrounded citation | Tighten evidence synthesis prompt & citation validator |
| `abstain_error` | False abstention or failure to abstain | Calibrate RRF score confidence floor (0.10) |
| `access_control_leak` | Unauthorized chunk or canary returned to restricted role | Enforce Layer 1 SQL pre-filtering and Layer 2 RLS |