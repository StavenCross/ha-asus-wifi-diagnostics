1. Avoid writing large, God-like files. Files should be capped at 300 lines of code or less unless they are just component/display/ui files. If a file exceeds the line limit, break it up into smaller, more manageable files
1a. As you work through the project, if you come across a file that exceeds the 300 line limit, but is not excluded by the above rule, add to your existing turn to break up the file, and let the user know at the close of the turn, always include regression testing when breaking a large file to ensure the project still works correctly.
2. When writing code, always create a fresh branch, before committing, review your changes and fix any errors. When you push code, merge the branch into main unless instructed otherwise.
3. Use subagents when possible to speed and parallelize development.
4. Be cautious and guarded about code implementation and planning, always review code written at the end of the turn, consider and inform user of implications and risks, this codebase is a critical production product used for real work.
5. Testing is how we ensure we are writing high quality code that doesn't break the project. Write tests for everything, run tests often, iterate your code until tests are green.
6. Before writing code, always review your skill set and utilize relevant skills to help write better code.
7. avoid duplicating logic. always check before and after writing code that you're not adding duplicate entry points, prefer shared helpers and extending existing functions or code where possible.
8. maintain strict boundries. keep your code clean,logical, unsurprising.
9. your project architecture should be dry and obvious, take the time if you extend or refactor to rename files and functions to reflect their current role in the project. Always write a regression test to ensure you don't break something.
10. docs/ should be and stay atomic. before the close of your turn, if you wrote, changed or modified code, make sure to check the relevant docs/ file and ensure it stays updated against your changes. if docs/ doesn't exist, create it and add atomic docs for the project.
11. Comments are how your future self stays aligned in the codebase against specific functions, they're what allows you to quickly and easily troubleshoot later. Write your comments as though this was an elixier project. Comments should describe not just what the code does, but the INTENT behind it. what params are allowed, how they should be used etc.
11a. if you come across a function or file without a comment, the comment is out of date etc, update the comment always before you end your turn.

--Below #Agent Notes, you may add helpful informtion for the project;
1. Do not add maps or the like, that kind of information belongs in docs/
2. this section is for things that are important that you always remember when working on this project (location of keys, how to use a special end point or relevant skills when developing the project.

  #Agent Notes



--below #surprising details for the user, you should add things you want me to review
1. did something unexpected happen? record it for me here
2. is there something you discovered that should be refactored, updated, changed? write it here.
3. occasionally, you should alert me to these notes so we can work on your suggestions.
#Surprising details for the user
