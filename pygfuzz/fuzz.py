#!/usr/bin/env python3
# Use a grammar to fuzz, using derivation trees

import random
import sys
import pudb
brk = pudb.set_trace
import string


# For debugging:
DEBUG = False
def log(s):
    if DEBUG:
        print(s() if callable(s) else s, file=sys.stderr, flush=True)

class GFuzz:
    def __init__(self, grammar):
        self.grammar = grammar
        self._expansion_to_children = {}
        self._symbol_min_cost ={}
        self._min_expansions = {}

    # The minimum cost of expansion of this symbol
    def symbol_min_cost(self, nt, seen=set()):
        if nt not in self._symbol_min_cost:
            self._symbol_min_cost[nt] = self.symbol_min_cost_(nt, seen)
        return self._symbol_min_cost[nt]

    def symbol_min_cost_(self, nt, seen=set()):
        expansions = self.grammar[nt]
        return min(self.min_expansions(e, seen | {nt}) for e in expansions)

    # The minimum cost of expansion of this rule
    def min_expansions(self, ex, seen=set()):
        if ex not in self._min_expansions:
            self._min_expansions[ex] = self.min_expansions_(ex, seen)
        return self._min_expansions[ex]

    def min_expansions_(self, ex, seen=set()):
        #log("minexpansions %s" % expansion)
        symbols  = [s for s in ex if self.is_symbol(s)]
        # at least one expansion has no variable to expand.
        if not symbols: return 1

        # if a variable present in the expansion is already in the stack, then it is
        # recursion
        if any(s in seen for s in symbols): return float('inf')
        # the value of a expansion is the sum of all expandable variables inside + 1
        cost = sum(self.symbol_min_cost(s, seen) for s in symbols) + 1
        #log("cost = %d" % cost)
        return cost

    # We create a derivation tree with nodes in the form (SYMBOL, CHILDREN)
    # where SYMBOL is either a nonterminal or terminal,
    # and CHILDREN is
    # - a list of children (for nonterminals)
    # - an empty list for terminals
    # - None for nonterminals that are yet to be expanded
    # Example:
    # ("$START", None) - the initial tree with just the root node
    # ("$START", [("$EXPR", None)]) - expanded once into $START -> $EXPR
    # ("$START", [("$EXPR", [("$EXPR", None]), (" + ", []]), ("$TERM", None])]) -
    #     expanded into $START -> $EXPR -> $EXPR + $TERM

    # Return an initialized tree
    def is_symbol(self, s):
        raise NotImplementedError

    # Convert an expansion rule to children
    def expansion_to_children(self, ex):
        if ex not in self._expansion_to_children:
            self._expansion_to_children[ex] = self.expansion_to_children_(ex)
        return self._expansion_to_children[ex]

    def expansion_to_children_(self, ex):
        log("Converting " + repr(ex))
        # strings contains all substrings -- both terminals and non-terminals such
        # that ''.join(strings) == expansion
        r = []
        for s in ex:
            if not s: continue
            if self.is_symbol(s):
                r.append((s, None) )
            else:
                #assert type(s) is tuple # choice list
                #for lchoice in s:
                choice, count = s
                assert isinstance(count, tuple)
                for i in range(random.choice(count)):
                    r.append((choice, []))
        return tuple(r)

    # Expand a node
    def expand_node(self, node, prefer_shortest_expansion):
        (symbol, children) = node
        log("Expanding " + repr(symbol))
        assert children is None

        # Fetch the possible expansions from grammar...
        expansions = self.grammar[symbol]

        possible_children_with_len = []
        for expansion in expansions:
            a = self.expansion_to_children(expansion)
            b = self.min_expansions(expansion, {symbol})
            possible_children_with_len.append((a, b))
        log('Expanding.1')
        min_len = min(s[1] for s in possible_children_with_len)

        # ...as well as the shortest ones
        shortest_children = [child for (child, clen) in possible_children_with_len
                                   if clen == min_len]

        log('Expanding.2')
        # Pick a child randomly
        if prefer_shortest_expansion:
            children = random.choice(shortest_children)
        else:
            # TODO: Consider preferring children not expanded yet,
            # and other forms of grammar coverage (or code coverage)
            children, _ = random.choice(possible_children_with_len)

        # Return with a new list
        return (symbol, children)

    # Count possible expansions -
    # that is, the number of (SYMBOL, None) nodes in the tree
    def possible_expansions(self, tree):
        (symbol, children) = tree
        if children is None:
            return 1

        number_of_expansions = sum(self.possible_expansions(c) for c in children)
        return number_of_expansions

    # short circuit. any will return for the first item that is true without
    # evaluating the rest.
    def any_possible_expansions(self, tree):
        (symbol, children) = tree
        if children is None: return True

        return any(self.any_possible_expansions(c) for c in children)

    # Expand the tree once
    def expand_tree_once(self, tree, prefer_shortest_expansion):
        log('Expand once %s %s' % (prefer_shortest_expansion, tree))
        (symbol, children) = tree
        if children is None:
            # Expand this node
            return self.expand_node(tree, prefer_shortest_expansion)

        log("Expanding tree " + repr(tree))

        # Find all children with possible expansions
        expandable_children = [i for (i, c) in enumerate(children) if self.any_possible_expansions(c)]

        # Select a random child
        # TODO: Various heuristics for choosing a child here,
        # e.g. grammar or code coverage
        child_to_be_expanded = random.choice(expandable_children)

        # Expand it
        new_child = self.expand_tree_once(children[child_to_be_expanded], prefer_shortest_expansion)

        new_children = (list(children[:child_to_be_expanded]) +
                        [new_child] +
                        list(children[child_to_be_expanded + 1:]))

        new_tree = (symbol, new_children)

        log("Expanding tree " + repr(tree) + " into " + repr(new_tree))

        return new_tree

    # Keep on applying productions
    # We limit production by the number of minimum expansions
    # alternate limits (e.g. length of overall string) are possible too
    def expand_tree(self, tree, max_symbols):
        # Stage 1: Expand until we reach the max number of symbols
        log("Expanding")
        while 0 < self.possible_expansions(tree) < max_symbols:
            tree = self.expand_tree_once(tree, False)
            log(lambda: self.all_terminals(tree))

        # Stage 2: Keep on expanding, but now focus on the shortest expansions
        log("Closing")
        while self.any_possible_expansions(tree):
            tree = self.expand_tree_once(tree, True)
            log(lambda: self.all_terminals(tree))

        return tree

    def to_str(self, v):
        if self.is_symbol(v): return str(v)
        elif type(v) is list: return ''.join([self.to_str(i) for i in v])
        elif type(v) is tuple:
            if len(v) > 0:
                return random.choice(v)
            return ''
        else: return str(v)

    # The tree as a string
    def all_terminals(self, tree):
        (symbol, children) = tree
        if children is None:
            # This is a nonterminal symbol not expanded yet
            return self.to_str(symbol)

        if len(children) == 0:
            # This is a terminal symbol
            return self.to_str(symbol)

        # This is an expanded symbol:
        # Concatenate all terminal symbols from all children
        return ''.join([self.all_terminals(c) for c in children])

    # All together
    def produce(self, start, max_symbols = 100):
        # Create an initial derivation tree
        tree = (start, None)
        log(tree)

        # Expand all nonterminals
        tree = self.expand_tree(tree, max_symbols)
        log(tree)

        # Return the string
        return self.all_terminals(tree)
